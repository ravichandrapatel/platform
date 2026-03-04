#!/usr/bin/env python3
"""
FILE_NAME: issues_bot.py
DESCRIPTION: Idempotent Issues Bot for GitHub: create, update, close, or upsert issues with
  tracking-ID deduplication, rate-limit resilience, and secondary delay for destructive ops.
  Stdlib only. Outputs issue-number and issue-url to GITHUB_OUTPUT.
VERSION: 1.0.0
EXIT_CODES: 0 = success, 1 = error (config, API, or validation)
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import quote
import urllib.error
import urllib.request

PREFIX = "[ISSUES-BOT]"
PROJECT_PREFIX = PREFIX
# Pause primary rate limit when remaining requests fall at or below this
RATE_LIMIT_PAUSE_THRESHOLD = 50
# Min/max delay (seconds) before POST/PATCH/DELETE to avoid secondary (abuse) rate limits
DESTRUCTIVE_DELAY_MIN = 0.1
DESTRUCTIVE_DELAY_MAX = 0.2
# Hidden footer tag for tracking ID (find our issues even if title changes); overridable via ISSUES_BOT_TRACKING_PREFIX
DEFAULT_TRACKING_PREFIX = "issues-bot:id"
# Default creator filter for list_issues (faster search); overridable via ISSUES_BOT_CREATOR_FILTER
DEFAULT_CREATOR_FILTER = "github-actions[bot]"


def _log(msg: str) -> None:
    """INTENT: Emit prefixed log line. INPUT: msg (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    print(f"{PREFIX} {msg}")


class GitHubApiError(Exception):
    """ROLE: Data. INTENT: Represent 4xx GitHub API error. INPUT: code (int), body (str). OUTPUT: N/A. SIDE_EFFECTS: None."""

    def __init__(self, code: int, body: str) -> None:
        self.code = code
        self.body = body
        try:
            data = json.loads(body) if body else {}
            self.message = (data.get("message") or "").strip() or body[:200]
        except Exception:
            self.message = (body or f"HTTP {code}")[:200]
        super().__init__(f"HTTP {code}: {self.message}")

    def reason(self) -> str:
        if self.code == 401:
            return "Unauthorized (token missing or invalid)"
        if self.code == 403:
            return "Forbidden (token lacks scope or rate limited)"
        if self.code == 404:
            return "Not found (repo or issue)"
        if 400 <= self.code < 500:
            return f"Client error {self.code}: {self.message}"
        return f"HTTP {self.code}: {self.message}"


class IssueSummary(TypedDict, total=False):
    number: int
    html_url: str
    title: str
    body: str
    state: str


def _tracking_prefix() -> str:
    """INTENT: Return tracking tag prefix from env or default. OUTPUT: str. SIDE_EFFECTS: Reads os.environ."""
    return (os.getenv("ISSUES_BOT_TRACKING_PREFIX", "") or DEFAULT_TRACKING_PREFIX).strip() or DEFAULT_TRACKING_PREFIX


def _build_body(user_body: str, tracking_id: str) -> str:
    """INTENT: Build issue body with standardized footer and hidden tracking ID for dedup.
    INPUT: user_body (str), tracking_id (str). OUTPUT: str. SIDE_EFFECTS: None."""
    payload = (user_body or "").strip()
    prefix = _tracking_prefix()
    footer = f"\n\n<!-- {prefix}:{tracking_id} -->"
    if not payload:
        return footer.strip()
    return payload + footer


def _body_contains_tracking_id(body: str, tracking_id: str) -> bool:
    """INTENT: Detect if body contains our tracking ID (tag or plain). INPUT: body, tracking_id. OUTPUT: bool. SIDE_EFFECTS: None."""
    if not body or not tracking_id:
        return False
    prefix = _tracking_prefix()
    tag = f"<!-- {prefix}:{tracking_id} -->"
    return tag in body or tracking_id in body


def _parse_repo(repo_input: str) -> tuple[str, str]:
    """INTENT: Return (owner, repo_name). INPUT: repo (owner/name or name). OUTPUT: (str, str). SIDE_EFFECTS: env read."""
    repo_input = (repo_input or "").strip()
    if "/" in repo_input:
        a, b = repo_input.split("/", 1)
        return a.strip(), b.strip()
    owner = os.getenv("GITHUB_REPOSITORY_OWNER", "").strip()
    if not owner and os.getenv("GITHUB_REPOSITORY"):
        owner = os.getenv("GITHUB_REPOSITORY", "").split("/", 1)[0].strip()
    return owner or "", repo_input


# ---------------------------------------------------------------------------
# API client: primary rate limit (X-RateLimit-Remaining), secondary delay (POST/PATCH/DELETE)
# ---------------------------------------------------------------------------

class GitHubApiClient:
    """ROLE: Service. INTENT: GitHub REST API with rate-limit pause and destructive-op delay. SIDE_EFFECTS: Network I/O."""

    def __init__(
        self,
        token: str,
        api_url: Optional[str] = None,
        destructive_delay: float = 0.15,
    ) -> None:
        self._token = token.strip()
        self._base_url = (api_url or os.getenv("GITHUB_API_URL", "https://api.github.com")).rstrip("/")
        self._destructive_delay = max(DESTRUCTIVE_DELAY_MIN, min(DESTRUCTIVE_DELAY_MAX, destructive_delay))

    def _maybe_pause_primary(self, headers: Any) -> None:
        """INTENT: Pause when X-RateLimit-Remaining <= threshold. INPUT: response headers. OUTPUT: None. SIDE_EFFECTS: time.sleep."""
        if headers is None:
            return
        try:
            remaining = headers.get("X-RateLimit-Remaining")
            if remaining is None:
                return
            left = int(remaining)
            if left > RATE_LIMIT_PAUSE_THRESHOLD:
                return
            reset = headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(0, int(reset) - int(time.time()))
                wait = min(wait, 300)
                if wait > 0:
                    _log(f"[DBG-920] Rate limit low ({left} left); pausing {wait}s until reset.")
                    time.sleep(wait)
            else:
                time.sleep(60)
        except (ValueError, TypeError):
            pass

    def _maybe_delay_destructive(self, method: str) -> None:
        """INTENT: Delay before POST/PATCH/DELETE to avoid secondary rate limits. SIDE_EFFECTS: time.sleep."""
        if method.upper() in ("POST", "PATCH", "PUT", "DELETE"):
            time.sleep(self._destructive_delay)

    def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """INTENT: Perform request; return JSON; raise GitHubApiError on 4xx. SIDE_EFFECTS: Network, sleep."""
        self._maybe_delay_destructive(method)
        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "issues-bot",
        }
        body_bytes = None
        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                self._maybe_pause_primary(resp.headers)
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            err_body = (e.read().decode("utf-8") if e.fp else "") or ""
            if hasattr(e, "headers") and e.headers:
                self._maybe_pause_primary(e.headers)
            if 400 <= e.code < 500:
                raise GitHubApiError(e.code, err_body) from e
            raise

    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        creator: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """INTENT: List issues with pagination (per_page=100). Filter by creator when set (e.g. github-actions[bot] for faster search).
        INPUT: owner, repo, state, optional creator. OUTPUT: list. SIDE_EFFECTS: Network."""
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            path = f"/repos/{owner}/{repo}/issues?state={state}&per_page=100&page={page}"
            if creator:
                path += f"&creator={quote(creator, safe='')}"
            data = self.request("GET", path)
            if not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < 100:
                break
            page += 1
        return out

    def get_issue(self, owner: str, repo: str, number: int) -> Optional[Dict[str, Any]]:
        """INTENT: Fetch single issue. OUTPUT: dict or None. SIDE_EFFECTS: Network."""
        data = self.request("GET", f"/repos/{owner}/{repo}/issues/{number}")
        return data if isinstance(data, dict) else None

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """INTENT: Create issue. Returns issue dict or None. SIDE_EFFECTS: Network."""
        payload: Dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = [lbl.strip() for lbl in labels if lbl.strip()]
        return self.request("POST", f"/repos/{owner}/{repo}/issues", payload)

    def update_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        body: Optional[str] = None,
        title: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """INTENT: PATCH issue (body, title, state, labels). SIDE_EFFECTS: Network."""
        payload: Dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if title is not None:
            payload["title"] = title
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = [lbl.strip() for lbl in labels if lbl.strip()]
        if not payload:
            return self.get_issue(owner, repo, number)
        return self.request("PATCH", f"/repos/{owner}/{repo}/issues/{number}", payload)

    def close_issue(self, owner: str, repo: str, number: int) -> Optional[Dict[str, Any]]:
        """INTENT: Close issue. SIDE_EFFECTS: Network."""
        return self.update_issue(owner, repo, number, state="closed")

    def add_comment(self, owner: str, repo: str, issue_number: int, body: str) -> Optional[Dict[str, Any]]:
        """INTENT: Add comment to issue. SIDE_EFFECTS: Network."""
        return self.request("POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", {"body": body})


def find_issue_by_tracking_id(
    client: GitHubApiClient,
    owner: str,
    repo: str,
    tracking_id: str,
    state: str = "open",
    creator: Optional[str] = None,
) -> Optional[IssueSummary]:
    """INTENT: Search open issues (paginated) for body containing tracking_id. Use creator filter when set for faster search.
    OUTPUT: IssueSummary or None. SIDE_EFFECTS: Network."""
    issues = client.list_issues(owner, repo, state=state, creator=creator)
    for i in issues:
        if i.get("pull_request"):
            continue
        b = (i.get("body") or "").strip()
        if _body_contains_tracking_id(b, tracking_id):
            return {
                "number": i.get("number", 0),
                "html_url": i.get("html_url", ""),
                "title": i.get("title", ""),
                "body": b,
                "state": i.get("state", "open"),
            }
    return None


def write_github_output(summary: IssueSummary) -> None:
    """INTENT: Write issue-number and issue-url to GITHUB_OUTPUT and legacy set-output. SIDE_EFFECTS: File, stdout."""
    num = summary.get("number")
    url = (summary.get("html_url") or "").strip()
    if num is None:
        return
    out_path = os.getenv("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"issue-number={num}\n")
            f.write(f"issue-url<<EOF\n{url}\nEOF\n")
    print(f"::set-output name=issue-number::{num}")
    print(f"::set-output name=issue-url::{url}")


def run(
    mode: str,
    repo: str,
    issue_title: str,
    tracking_id: str,
    issue_body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    token: Optional[str] = None,
    api_url: Optional[str] = None,
    destructive_delay: float = 0.15,
) -> int:
    """INTENT: Execute mode (create, update, close, upsert). OUTPUT: exit code. SIDE_EFFECTS: Network, GITHUB_OUTPUT."""
    _log("[DBG-000] Starting Issues Bot...")
    owner, repo_name = _parse_repo(repo)
    if not owner or not repo_name:
        _log("[DBG-910] Could not resolve owner/repo. Set GITHUB_REPOSITORY_OWNER or use owner/repo format.")
        return 1

    token = (token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not token:
        _log("[DBG-911] GITHUB_TOKEN or GH_TOKEN must be set.")
        return 1

    client = GitHubApiClient(token, api_url=api_url, destructive_delay=destructive_delay)
    body_with_footer = _build_body(issue_body or "", tracking_id)
    creator_filter = (os.getenv("ISSUES_BOT_CREATOR_FILTER", DEFAULT_CREATOR_FILTER) or "").strip() or None

    if mode == "create":
        created = client.create_issue(owner, repo_name, issue_title, body_with_footer, labels=labels)
        if not created or not isinstance(created, dict):
            _log("[DBG-922] Failed to create issue.")
            return 1
        write_github_output(created)
        _log(f"[DBG-001] Created issue #{created.get('number')} ({created.get('html_url')}).")
        return 0

    if mode == "close":
        existing = find_issue_by_tracking_id(client, owner, repo_name, tracking_id, state="open", creator=creator_filter)
        if not existing:
            _log("[DBG-002] No open issue found with this tracking ID; nothing to close.")
            return 0
        client.close_issue(owner, repo_name, existing["number"])
        _log(f"[DBG-003] Closed issue #{existing['number']}.")
        return 0

    if mode == "update":
        existing = find_issue_by_tracking_id(client, owner, repo_name, tracking_id, state="open", creator=creator_filter)
        if not existing:
            _log("[DBG-912] No open issue found with this tracking ID; nothing to update.")
            return 1
        updated = client.update_issue(
            owner, repo_name, existing["number"],
            body=body_with_footer,
            title=issue_title,
            labels=labels,
        )
        if not updated:
            _log("[DBG-922] Failed to update issue.")
            return 1
        write_github_output(updated)
        _log(f"[DBG-004] Updated issue #{updated.get('number')}.")
        return 0

    if mode == "upsert":
        existing = find_issue_by_tracking_id(client, owner, repo_name, tracking_id, state="open", creator=creator_filter)
        if existing:
            updated = client.update_issue(
                owner, repo_name, existing["number"],
                body=body_with_footer,
                title=issue_title,
                labels=labels,
            )
            if not updated:
                _log("[DBG-922] Failed to update existing issue.")
                return 1
            write_github_output(updated)
            _log(f"[DBG-005] Upsert: updated issue #{updated.get('number')}.")
            return 0
        created = client.create_issue(owner, repo_name, issue_title, body_with_footer, labels=labels)
        if not created or not isinstance(created, dict):
            _log("[DBG-922] Failed to create issue.")
            return 1
        write_github_output(created)
        _log(f"[DBG-006] Upsert: created issue #{created.get('number')} ({created.get('html_url')}).")
        return 0

    _log(f"[DBG-913] Unknown mode: {mode}. Use create, update, close, or upsert.")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    """INTENT: Parse args and env, run bot. OUTPUT: exit code. SIDE_EFFECTS: Network, stdout, GITHUB_OUTPUT."""
    parser = argparse.ArgumentParser(description="Issues Bot: create, update, close, or upsert issues with tracking ID.")
    parser.add_argument("--mode", choices=["create", "update", "close", "upsert"], required=True, help="create, update, close, or upsert")
    parser.add_argument("--repo", required=True, help="Repository (owner/repo or name)")
    parser.add_argument("--issue-title", required=True, dest="issue_title", help="Issue title")
    parser.add_argument("--tracking-id", required=True, dest="tracking_id", help="Unique ID for deduplication (stored in body footer)")
    parser.add_argument("--issue-body", default=None, dest="issue_body", help="Issue body (markdown); footer with tracking ID is appended")
    parser.add_argument("--labels", default=None, help="Comma-separated labels to apply")
    args = parser.parse_args(argv)

    labels_list: Optional[List[str]] = None
    if args.labels:
        labels_list = [s.strip() for s in args.labels.split(",") if s.strip()]

    delay_str = os.getenv("ISSUES_BOT_DESTRUCTIVE_DELAY", "0.15").strip()
    try:
        destructive_delay = max(DESTRUCTIVE_DELAY_MIN, min(DESTRUCTIVE_DELAY_MAX, float(delay_str or "0.15")))
    except ValueError:
        destructive_delay = 0.15

    try:
        return run(
            mode=args.mode,
            repo=args.repo,
            issue_title=args.issue_title,
            tracking_id=args.tracking_id,
            issue_body=args.issue_body or os.getenv("ISSUES_BOT_BODY"),
            labels=labels_list,
            token=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"),
            api_url=os.getenv("GITHUB_API_URL"),
            destructive_delay=destructive_delay,
        )
    except GitHubApiError as e:
        _log(f"[DBG-923] {e.reason()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
