#!/usr/bin/env python3
"""
FILE_NAME: prbot.py
DESCRIPTION: Create or re-use a pull request in a target repository. Zero-dependency (stdlib only).
  Supports same-repo PRs or management repo opening PR in another repo; optional owner:branch for head.
VERSION: 1.0.0
EXIT_CODES: 0 = success, 1 = error (API, validation, or runtime)
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TypedDict
import urllib.error
import urllib.request
from urllib.parse import quote

PROJECT_PREFIX = "[PROJECT-PRBOT]"


class GitHubApiError(Exception):
    """ROLE: Data. INTENT: Represent 4xx GitHub API error for clear reporting.
    INPUT: code (int), body (str). OUTPUT: N/A. SIDE_EFFECTS: None."""

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
        """Short human-readable reason for logs."""
        if self.code == 401:
            return "Unauthorized (token missing or invalid)"
        if self.code == 403:
            return "Forbidden (token lacks repo access or rate limited)"
        if self.code == 404:
            return "Not found (repo or branch does not exist)"
        if self.code == 422:
            return f"Validation failed (e.g. branch not found): {self.message}"
        if 400 <= self.code < 500:
            return f"Client error {self.code}: {self.message}"
        return f"HTTP {self.code}: {self.message}"


class PullRequestSummary(TypedDict, total=False):
    number: int
    html_url: str
    title: str
    head_ref: str
    base_ref: str


def _log(message: str) -> None:
    """INTENT: Print a message with the project prefix. INPUT: message (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    print(f"{PROJECT_PREFIX}{message}")


def _write_github_output(pr_summary: PullRequestSummary) -> None:
    """INTENT: Write pr-number and pr-url for GitHub Actions (GITHUB_OUTPUT + legacy set-output).
    INPUT: pr_summary (dict with number, html_url). OUTPUT: None. SIDE_EFFECTS: File, stdout."""
    num = pr_summary.get("number")
    url = (pr_summary.get("html_url") or "").strip()
    if num is None:
        return
    out_path = os.getenv("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"pr-number={num}\n")
            f.write(f"pr-url<<EOF\n{url}\nEOF\n")
    print(f"::set-output name=pr-number::{num}")
    print(f"::set-output name=pr-url::{url}")


class GitHubApiClient:
    """ROLE: Service. INTENT: Minimal GitHub REST API client (stdlib urllib).
    INPUT: token, api_url. OUTPUT: N/A. SIDE_EFFECTS: Network I/O."""

    def __init__(self, token: str, api_url: Optional[str] = None) -> None:
        self._token = token.strip()
        base = api_url or os.getenv("GITHUB_API_URL", "https://api.github.com")
        # Ensure no trailing slash for safe concatenation
        self._base_url = base.rstrip("/")

    def request_json(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make an HTTP request and return parsed JSON. Raises GitHubApiError on 4xx."""
        url = f"{self._base_url}{path}"
        body_bytes: Optional[bytes] = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "prbot",
        }
        if data is not None:
            body_str = json.dumps(data)
            body_bytes = body_str.encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = "<no body>"
            # _log("[ERR-T-01] GitHub API 4xx/5xx")
            _log(
                f"[DBG-900] GitHub API error {exc.code} for {method} {path}: {err_body}"
            )
            if 400 <= exc.code < 500:
                raise GitHubApiError(exc.code, err_body) from exc
            return None
        except urllib.error.URLError as exc:
            # _log("[ERR-T-02] Network error")
            _log(f"[DBG-901] Network error for {method} {path}: {exc}")
            return None


def _split_repo(repo_input: str) -> Tuple[str, str]:
    """INTENT: Return (owner, repo_name) from input; use env for owner if repo is simple name.
    INPUT: repo_input (str). OUTPUT: Tuple[str, str]. SIDE_EFFECTS: Reads os.environ."""
    repo_input = (repo_input or "").strip()
    if "/" in repo_input:
        owner, name = repo_input.split("/", 1)
        owner, name = owner.strip(), name.strip()
        if not name:
            return owner, ""  # main() will reject empty repo_name
        return owner, name

    owner = os.getenv("GITHUB_REPOSITORY_OWNER", "").strip()
    if not owner:
        repo_env = os.getenv("GITHUB_REPOSITORY", "")
        if "/" in repo_env:
            owner = repo_env.split("/", 1)[0].strip()
    if not owner:
        return "", repo_input
    return owner, repo_input


def _compose_body(user_payload: str) -> str:
    """INTENT: Compose PR body by appending standard footer to optional payload.
    INPUT: user_payload (str). OUTPUT: str. SIDE_EFFECTS: None."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d%H%M%SZ")
    footer = f"Generated by Automation | ID: [project-prbot-{timestamp}]"

    payload = (user_payload or "").strip()
    if not payload:
        return footer
    return f"{payload}\n\n{footer}"


def _head_key(pr_head: Dict[str, Any]) -> str:
    """INTENT: Build comparable key for PR head (owner:ref or ref).
    INPUT: pr_head (Dict). OUTPUT: str. SIDE_EFFECTS: None."""
    ref = (pr_head.get("ref") or "").strip()
    repo = pr_head.get("repo") or {}
    owner = (repo.get("owner") or {}).get("login") or (pr_head.get("user") or {}).get("login") or ""
    if owner and ref:
        return f"{owner}:{ref}"
    return ref


def find_existing_pr(
    client: GitHubApiClient,
    owner: str,
    repo: str,
    source_branch: str,
    target_branch: str,
) -> Optional[PullRequestSummary]:
    """INTENT: Search for an open PR whose head/base match. source_branch may be 'ref' or 'owner:ref'.
    INPUT: client, owner, repo, source_branch, target_branch. OUTPUT: Optional[PullRequestSummary]. SIDE_EFFECTS: Network."""
    # _log("[T-01] Checking for existing PR")
    _log(
        f"[DBG-003] Checking for existing PR on {owner}/{repo} "
        f"for head='{source_branch}' base='{target_branch}'..."
    )

    # Optional: filter by head when cross-repo (owner:branch) to reduce pages
    head_param = ""
    if ":" in source_branch:
        head_param = f"&head={quote(source_branch)}"

    page = 1
    per_page = 100
    max_pages = 50  # safety cap (~5000 PRs); stop when no more data
    while page <= max_pages:
        path = (
            f"/repos/{owner}/{repo}/pulls"
            f"?state=open&per_page={per_page}&page={page}{head_param}"
        )
        data = client.request_json("GET", path)
        if not data or not isinstance(data, list):
            break

        for pr in data:
            head = pr.get("head") or {}
            base = pr.get("base") or {}
            base_ref = base.get("ref", "")
            head_key = _head_key(head)
            head_matches = (
                head_key == source_branch
                if ":" in source_branch
                else head.get("ref") == source_branch
            )
            if head_matches and base_ref == target_branch:
                summary: PullRequestSummary = {
                    "number": pr.get("number", 0),
                    "html_url": pr.get("html_url", ""),
                    "title": pr.get("title", ""),
                    "head_ref": head_key,
                    "base_ref": base_ref,
                }
                _log(
                    f"[DBG-004] Existing PR found: #{summary['number']} "
                    f"({summary['html_url']}). Skipping creation."
                )
                return summary

        if len(data) < per_page:
            break
        page += 1

    _log("[DBG-005] No existing PR found.")
    return None


def branch_exists(
    client: GitHubApiClient,
    owner: str,
    repo: str,
    branch: str,
) -> bool:
    """INTENT: Optional safety check that head branch exists before creating PR.
    INPUT: client, owner, repo, branch (ref name without refs/heads/). OUTPUT: bool. SIDE_EFFECTS: Network."""
    path = f"/repos/{owner}/{repo}/git/ref/heads/{quote(branch, safe='')}"
    try:
        data = client.request_json("GET", path)
        return isinstance(data, dict) and data.get("ref", "").endswith(f"/{branch}")
    except GitHubApiError:
        return False


def create_pull_request(
    client: GitHubApiClient,
    owner: str,
    repo: str,
    title: str,
    source_branch: str,
    target_branch: str,
    body: str,
) -> Optional[PullRequestSummary]:
    """INTENT: Create a new pull request and return summary, or None on failure.
    INPUT: client, owner, repo, title, source_branch, target_branch, body. OUTPUT: Optional[PullRequestSummary]. SIDE_EFFECTS: Network."""
    _log(
        f"[DBG-006] Creating PR on {owner}/{repo}: "
        f"head='{source_branch}', base='{target_branch}'"
    )
    path = f"/repos/{owner}/{repo}/pulls"
    payload: Dict[str, Any] = {
        "title": title,
        "head": source_branch,
        "base": target_branch,
        "body": body,
    }
    pr = client.request_json("POST", path, data=payload)
    if not isinstance(pr, dict):
        _log("[DBG-907] Unexpected response when creating PR (no JSON object returned).")
        return None

    summary: PullRequestSummary = {
        "number": pr.get("number", 0),
        "html_url": pr.get("html_url", ""),
        "title": pr.get("title", ""),
        "head_ref": source_branch,
        "base_ref": target_branch,
    }
    _log(
        f"[DBG-007] PR created successfully: #{summary['number']} "
        f"({summary['html_url']})."
    )
    return summary


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PR Bot")
    parser.add_argument("--repo", required=True, help="Target repo (owner/repo or name)")
    parser.add_argument("--title", required=True, help="Pull request title")
    parser.add_argument("--source-branch", required=True, help="Source branch name (head)")
    parser.add_argument(
        "--target-branch",
        default="main",
        help="Target branch name (base); default: main",
    )
    parser.add_argument(
        "--payload",
        default=None,
        help=(
            "Optional PR body payload. If omitted, PRBOT_PAYLOAD env var is used "
            "if present. standard footer is always appended."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """INTENT: Parse args, resolve repo, find or create PR. INPUT: argv (optional). OUTPUT: int exit code. SIDE_EFFECTS: Network, stdout."""
    # _log("[T-01] Starting PR Bot")
    _log("[DBG-000] Starting PR Bot (prbot)...")

    args = parse_args(argv)

    token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
    if not token:
        _log(
            "[DBG-910] Missing GITHUB_TOKEN in environment. "
            "Set it via action input github_token."
        )
        return 1

    owner, repo_name = _split_repo(args.repo)
    if not owner or not repo_name:
        _log(
            f"[DBG-911] Unable to resolve owner/repo from input '{args.repo}'. "
            "Check repo format."
        )
        return 1

    user_payload = args.payload
    if user_payload is None:
        user_payload = os.getenv("PRBOT_PAYLOAD", "")

    body = _compose_body(user_payload)

    api_url = os.getenv("GITHUB_API_URL")
    client = GitHubApiClient(token=token, api_url=api_url)

    _log(
        f"[DBG-001] Repo resolved to {owner}/{repo_name}; "
        f"source='{args.source_branch}', target='{args.target_branch}'."
    )

    try:
        existing = find_existing_pr(
            client=client,
            owner=owner,
            repo=repo_name,
            source_branch=args.source_branch,
            target_branch=args.target_branch,
        )
        if existing is not None:
            _write_github_output(existing)
            return 0

        # Optional safety: ensure head branch exists (same-repo only)
        if ":" not in args.source_branch:
            if not branch_exists(client, owner, repo_name, args.source_branch):
                _log(
                    f"[DBG-914] Branch '{args.source_branch}' not found in {owner}/{repo_name}. "
                    "Push the branch first or check the name."
                )
                return 1

        created = create_pull_request(
            client=client,
            owner=owner,
            repo=repo_name,
            title=args.title,
            source_branch=args.source_branch,
            target_branch=args.target_branch,
            body=body,
        )
        if created is None:
            _log("[DBG-912] Failed to create pull request.")
            return 1

        _write_github_output(created)
        _log("[DBG-002] PR Bot completed successfully.")
        return 0
    except GitHubApiError as e:
        # _log("[ERR-T-03] GitHub API error in main")
        _log(f"[DBG-913] {e.reason()}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
