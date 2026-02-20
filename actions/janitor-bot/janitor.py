#!/usr/bin/env python3
"""
Janitor Bot: scan (and optionally cleanup) stale branches and PRs.
Supports: one repo, multiple repos, entire org, or repos filtered by topic (tag).
Configuration is read from environment variables (set by GitHub Actions from workflow inputs).
Uses only stdlib: os, json, urllib.request, re, argparse, datetime, time.
Handles API throttling (rate limits, retry with backoff) and batches work where possible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

# Scope: org = all org repos, repo = single repo, repos = multiple repos, topic = org repos with topic
SCOPE_ORG = "org"
SCOPE_REPO = "repo"
SCOPE_REPOS = "repos"
SCOPE_TOPIC = "topic"


def _parse_repo_spec(spec: str, default_owner: str) -> tuple[str, str]:
    """Return (owner, repo_name). spec is either 'repo-name' or 'owner/repo-name'."""
    s = spec.strip()
    if "/" in s:
        parts = s.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return default_owner, s


def get_config() -> dict:
    """
    Parse configuration from environment variables (GitHub Action inputs mapped to env).
    Converts string inputs to correct types. Compiles BRANCH_EXCLUDE_REGEX for performance.
    """
    branch_stale = os.getenv("BRANCH_STALE_DAYS", "45")
    pr_stale = os.getenv("PR_STALE_DAYS", "30")
    pkg_keep = os.getenv("PKG_KEEP_COUNT", "5")

    exclude_labels_str = os.getenv("PR_EXCLUDE_LABELS", "pinned")
    exclude_labels = [s.strip() for s in exclude_labels_str.split(",") if s.strip()]

    exclude_regex_str = os.getenv("BRANCH_EXCLUDE_REGEX", r"^(main|master|develop)$")
    exclude_regex_compiled = re.compile(exclude_regex_str)

    scope = os.getenv("SCOPE", SCOPE_ORG).strip().lower() or SCOPE_ORG
    org = os.getenv("ORG_NAME", "").strip()
    single_repo = os.getenv("REPO", "").strip()
    multi_repos_str = os.getenv("REPOS", "").strip()
    repo_topic = os.getenv("REPO_TOPIC", os.getenv("TOPIC", "")).strip()

    # REPOS: comma or newline separated
    repos_list: list[str] = []
    if multi_repos_str:
        for part in re.split(r"[\n,]", multi_repos_str):
            if part.strip():
                repos_list.append(part.strip())

    return {
        "branches": {
            "stale_days": int(branch_stale) if str(branch_stale).strip() else 45,
            "exclude_regex": exclude_regex_str,
            "exclude_regex_compiled": exclude_regex_compiled,
            "protect_pr": os.getenv("BRANCH_PROTECT_PR", "true").strip().lower() == "true",
        },
        "prs": {
            "stale_days": int(pr_stale) if str(pr_stale).strip() else 30,
            "exclude_labels": exclude_labels,
        },
        "packages": {
            "keep_versions": int(pkg_keep) if str(pkg_keep).strip() else 5,
        },
        "org": org,
        "token": os.getenv("GH_TOKEN", "").strip(),
        "dry_run": os.getenv("DRY_RUN", "true").strip().lower() == "true",
        "scope": scope,
        "repo": single_repo,
        "repos": repos_list,
        "repo_topic": repo_topic,
    }


# ---------------------------------------------------------------------------
# Rate limiting and API client (throttling, retry, batching-friendly)
# ---------------------------------------------------------------------------

class RateLimiter:
    """
    Tracks GitHub API rate limit from response headers and waits when needed.
    Uses X-RateLimit-Remaining, X-RateLimit-Reset; respects Retry-After on 429/403.
    """
    DEFAULT_MIN_REMAINING = 20
    MAX_RETRIES = 4
    RETRY_BACKOFF_BASE = 60

    def __init__(self, min_remaining: int | None = None) -> None:
        self.min_remaining = min_remaining or self.DEFAULT_MIN_REMAINING
        self._remaining: int | None = None
        self._reset_epoch: int | None = None

    def _get_header(self, headers: object, key: str) -> str | None:
        """Get header value; try canonical and lowercase key (HTTP headers are case-insensitive)."""
        if not hasattr(headers, "get"):
            return None
        v = headers.get(key)
        if v is not None:
            return v
        return headers.get(key.lower())

    def update_from_headers(self, headers: object) -> None:
        """Update state from response headers (e.g. req.info() or response.headers)."""
        remaining = self._get_header(headers, "X-RateLimit-Remaining")
        reset = self._get_header(headers, "X-RateLimit-Reset")
        if remaining is not None:
            try:
                self._remaining = int(remaining)
            except (TypeError, ValueError):
                pass
        if reset is not None:
            try:
                self._reset_epoch = int(reset)
            except (TypeError, ValueError):
                pass

    def maybe_wait(self) -> None:
        """If remaining is below threshold, sleep until reset time."""
        if self._remaining is not None and self._remaining < self.min_remaining and self._reset_epoch is not None:
            now = int(time.time())
            wait = self._reset_epoch - now
            if wait > 0:
                print(f"⏳ Rate limit low ({self._remaining} remaining); waiting {wait}s until reset")
                time.sleep(wait)
                self._remaining = None

    @staticmethod
    def retry_after_seconds(headers: object) -> int | None:
        """Return Retry-After in seconds if present."""
        if not hasattr(headers, "get"):
            return None
        v = headers.get("Retry-After") or headers.get("retry-after")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def reset_epoch_from_headers(headers: object) -> int | None:
        """Return X-RateLimit-Reset epoch from headers."""
        if not hasattr(headers, "get"):
            return None
        v = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None


class GitHubApiClient:
    """
    GitHub REST API client with rate-limit awareness and retry on 403/429.
    All requests go through request(); RateLimiter is updated after each response.
    """
    def __init__(self, token: str, rate_limiter: RateLimiter | None = None) -> None:
        self._token = token
        self._limiter = rate_limiter or RateLimiter()

    def request(
        self,
        url: str,
        method: str = "GET",
        data: dict | None = None,
    ) -> dict | list | None:
        """Perform request; retry on 403/429 with backoff; update rate limiter; return JSON body."""
        last_error: Exception | None = None
        for attempt in range(RateLimiter.MAX_RETRIES):
            self._limiter.maybe_wait()
            req = urllib.request.Request(url, method=method)
            req.add_header("Authorization", f"token {self._token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            if data is not None:
                req.add_header("Content-Type", "application/json")
                data_bytes = json.dumps(data).encode("utf-8")
            else:
                data_bytes = None
            try:
                with urllib.request.urlopen(req, data=data_bytes, timeout=30) as res:
                    self._limiter.update_from_headers(res.headers)
                    self._limiter.maybe_wait()
                    body = res.read().decode()
                    return json.loads(body) if method != "DELETE" else {}
            except urllib.error.HTTPError as e:
                last_error = e
                code = e.code
                headers = e.headers if e.headers is not None else {}
                self._limiter.update_from_headers(headers)
                if code in (403, 429):
                    wait = RateLimiter.retry_after_seconds(headers)
                    if wait is None:
                        reset = RateLimiter.reset_epoch_from_headers(headers)
                        wait = (reset - int(time.time())) if reset else RateLimiter.RETRY_BACKOFF_BASE
                    wait = max(1, min(wait, 300))
                    print(f"⚠️ API rate limit ({code}); retry in {wait}s (attempt {attempt + 1}/{RateLimiter.MAX_RETRIES})")
                    time.sleep(wait)
                    continue
                print(f"API Error: {e}")
                return None
            except Exception as e:
                last_error = e
                print(f"API Error: {e}")
                return None
        if last_error:
            print(f"API Error (max retries): {last_error}")
        return None


class RepoResolver:
    """Resolves the list of (owner, repo_name) to scan based on scope and config."""
    def __init__(self, config: dict, api_client: GitHubApiClient) -> None:
        self._config = config
        self._client = api_client

    def get_repos(self) -> list[tuple[str, str]]:
        """Return list of (owner, repo_name) for the configured scope."""
        scope = self._config.get("scope", SCOPE_ORG)
        org = self._config.get("org", "")
        result: list[tuple[str, str]] = []

        if scope == SCOPE_REPO:
            spec = self._config.get("repo", "").strip()
            if not spec:
                print("Error: SCOPE=repo requires REPO to be set")
                raise SystemExit(1)
            if "/" not in spec and not org:
                print("Error: SCOPE=repo with REPO as name requires ORG_NAME (or use owner/repo)")
                raise SystemExit(1)
            result.append(_parse_repo_spec(spec, org or ""))

        elif scope == SCOPE_REPOS:
            reps = self._config.get("repos", [])
            if not reps:
                print("Error: SCOPE=repos requires REPOS to be set (comma or newline separated)")
                raise SystemExit(1)
            if any("/" not in s for s in reps) and not org:
                print("Error: SCOPE=repos with repo names (no owner/) requires ORG_NAME")
                raise SystemExit(1)
            for spec in reps:
                result.append(_parse_repo_spec(spec, org or ""))

        elif scope == SCOPE_TOPIC:
            topic = self._config.get("repo_topic", "").strip()
            if not topic or not org:
                print("Error: SCOPE=topic requires ORG_NAME and REPO_TOPIC (or TOPIC) to be set")
                raise SystemExit(1)
            q = f"org:{org} topic:{topic}"
            url = f"https://api.github.com/search/repositories?q={quote(q)}&per_page=100"
            data = self._client.request(url)
            if not data or not isinstance(data, dict):
                print("Error: Could not search repos by topic")
                raise SystemExit(1)
            for r in data.get("items", []):
                full = r.get("full_name", "")
                if full and "/" in full:
                    owner, repo_name = full.split("/", 1)
                    result.append((owner, repo_name))

        else:
            if not org:
                print("Error: SCOPE=org requires ORG_NAME to be set")
                raise SystemExit(1)
            repos_data = self._client.request(
                f"https://api.github.com/orgs/{org}/repos?per_page=100&type=all"
            )
            if repos_data is not None and isinstance(repos_data, list):
                for r in repos_data:
                    name = r.get("name")
                    if name:
                        result.append((org, name))
            else:
                print("Error: Could not list org repos")
                raise SystemExit(1)

        return result


class JanitorBot:
    """Scans (and optionally cleans) stale branches/PRs; uses GitHubApiClient for throttling and retries."""
    def __init__(self, config: dict, api_client: GitHubApiClient) -> None:
        self.config = config
        self._api = api_client
        self.report: dict = {"branches": [], "prs": [], "packages": []}

    def scan_branches(self, owner: str, repo: str) -> None:
        rules = self.config["branches"]
        url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
        branches = self._api.request(url)
        if not branches:
            return

        threshold = datetime.now(tz=timezone.utc) - timedelta(days=rules["stale_days"])
        regex = rules["exclude_regex_compiled"]

        for b in branches:
            name = b["name"]
            if regex.match(name):
                continue
            if b.get("protected", False):
                continue

            if rules["protect_pr"]:
                pr_url = (
                    f"https://api.github.com/repos/{owner}/{repo}/pulls"
                    f"?state=open&head={owner}:{name}&per_page=1"
                )
                prs = self._api.request(pr_url)
                if prs and len(prs) > 0:
                    continue

            c_data = self._api.request(b["commit"]["url"])
            if not c_data:
                continue
            date_str = c_data["commit"]["committer"]["date"].replace("Z", "+00:00")
            try:
                last_date = datetime.fromisoformat(date_str)
            except ValueError:
                last_date = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)

            if last_date < threshold:
                self.report["branches"].append({
                    "repo": f"{owner}/{repo}",
                    "name": name,
                    "owner": c_data["commit"]["committer"].get("name", "unknown"),
                    "days": (datetime.now(tz=timezone.utc) - last_date).days,
                })

    def generate_report(self) -> None:
        """Write Markdown report; explicitly state the thresholds used for the scan."""
        cfg = self.config
        branch_days = cfg["branches"]["stale_days"]
        pr_days = cfg["prs"]["stale_days"]
        pkg_keep = cfg["packages"]["keep_versions"]
        exclude_regex = cfg["branches"]["exclude_regex"]
        exclude_labels = ", ".join(cfg["prs"]["exclude_labels"]) or "(none)"
        scope_desc = cfg.get("scope", SCOPE_ORG)

        with open("janitor_report.md", "w", encoding="utf-8") as f:
            f.write("# Janitor Bot Report\n\n")
            f.write("## Thresholds used for this scan\n\n")
            f.write("| Rule | Value |\n|------|-------|\n")
            f.write(f"| Scope | `{scope_desc}` |\n")
            f.write(f"| Branch stale (days) | `{branch_days}` |\n")
            f.write(f"| Branch exclude regex | `{exclude_regex}` |\n")
            f.write("| Protected branches | **never touched** |\n")
            f.write(f"| PR stale (days) | `{pr_days}` |\n")
            f.write(f"| PR exclude labels | `{exclude_labels}` |\n")
            f.write(f"| Package versions to keep | `{pkg_keep}` |\n")
            f.write(f"| Dry run | `{cfg['dry_run']}` |\n\n")

            if self.report["branches"]:
                f.write("## Stale branches\n\n")
                f.write("| Repo | Branch | Owner | Days stale |\n")
                f.write("|------|--------|-------|------------|\n")
                for b in self.report["branches"]:
                    f.write(f"| {b['repo']} | {b['name']} | {b['owner']} | {b['days']} |\n")
                f.write("\n")
            else:
                f.write("## Stale branches\n\nNo stale branches found.\n\n")

        print("Report written to janitor_report.md")


class ScanRunner:
    """Runs branch scan over a list of repos with rate-limit awareness (batch-friendly)."""
    def __init__(self, bot: JanitorBot, batch_delay_seconds: float = 0.0) -> None:
        self._bot = bot
        self._batch_delay = max(0.0, batch_delay_seconds)

    def run(self, repos: list[tuple[str, str]], mode: str) -> None:
        for i, (owner, repo_name) in enumerate(repos):
            if mode == "scan":
                self._bot.scan_branches(owner, repo_name)
            if self._batch_delay > 0 and i < len(repos) - 1:
                time.sleep(self._batch_delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Janitor Bot: scan or cleanup stale branches/PRs")
    parser.add_argument("--mode", choices=["scan", "cleanup"], required=True)
    args = parser.parse_args()

    config = get_config()
    if not config["token"]:
        print("Error: GH_TOKEN must be set (e.g. via workflow env)")
        raise SystemExit(1)
    scope = config.get("scope", SCOPE_ORG)
    if scope == SCOPE_ORG or scope == SCOPE_TOPIC:
        if not config["org"]:
            print("Error: ORG_NAME must be set for scope=org or scope=topic")
            raise SystemExit(1)
    elif scope == SCOPE_REPO and not config.get("repo"):
        if not config["org"]:
            print("Error: ORG_NAME or REPO must be set for scope=repo")
            raise SystemExit(1)
    elif scope == SCOPE_REPOS and not config.get("repos"):
        if not config["org"]:
            print("Error: ORG_NAME (default owner) or REPOS must be set for scope=repos")
            raise SystemExit(1)

    rate_limiter = RateLimiter()
    api_client = GitHubApiClient(config["token"], rate_limiter)
    resolver = RepoResolver(config, api_client)
    bot = JanitorBot(config, api_client)
    repos_to_scan = resolver.get_repos()

    batch_delay_str = os.getenv("BATCH_DELAY_SECONDS", "0").strip()
    try:
        batch_delay = float(batch_delay_str) if batch_delay_str else 0.0
    except ValueError:
        batch_delay = 0.0
    runner = ScanRunner(bot, batch_delay_seconds=batch_delay)
    runner.run(repos_to_scan, args.mode)

    if args.mode == "scan":
        bot.generate_report()


if __name__ == "__main__":
    main()
