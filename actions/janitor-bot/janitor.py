#!/usr/bin/env python3
"""
FILE_NAME: janitor.py
DESCRIPTION: Scan and optionally cleanup stale branches, PRs, artifacts, packages.
  Supports one repo, multiple repos, org, or topic filter. Config from env (GitHub Action inputs). Stdlib only.
VERSION: 1.0.0
EXIT_CODES: 0 = success, 1 = error (config, API, or runtime)
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import fnmatch
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

PROJECT_PREFIX = "[JANITOR-BOT]"


def _log(message: str) -> None:
    """INTENT: Print a message with the project prefix (breadcrumb/debug). INPUT: message (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    print(f"{PROJECT_PREFIX} {message}")


def _parse_repo_spec(spec: str, default_owner: str) -> tuple[str, str]:
    """INTENT: Return (owner, repo_name). spec is 'repo-name' or 'owner/repo-name'.
    INPUT: spec (str), default_owner (str). OUTPUT: tuple[str, str]. SIDE_EFFECTS: None."""
    s = spec.strip()
    if "/" in s:
        parts = s.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return default_owner, s


def get_config() -> dict:
    """INTENT: Parse configuration from env (GitHub Action inputs); compile regex and types.
    INPUT: None (reads os.environ). OUTPUT: dict. SIDE_EFFECTS: Reads os.environ."""
    branch_stale = os.getenv("BRANCH_STALE_DAYS", "45")
    pr_stale = os.getenv("PR_STALE_DAYS", "30")
    pkg_keep = os.getenv("PKG_KEEP_COUNT", "5")

    exclude_labels_str = os.getenv("PR_EXCLUDE_LABELS", "pinned")
    exclude_labels = [s.strip() for s in exclude_labels_str.split(",") if s.strip()]

    exclude_regex_str = os.getenv("BRANCH_EXCLUDE_REGEX", r"^(main|master|develop)$")
    exclude_regex_compiled = re.compile(exclude_regex_str)
    branch_include_pattern = os.getenv("BRANCH_INCLUDE_PATTERN", "").strip() or "*"

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

    cleanup_branches = os.getenv("CLEANUP_BRANCHES", "true").strip().lower() == "true"
    cleanup_artifacts = os.getenv("CLEANUP_ARTIFACTS", "false").strip().lower() == "true"
    cleanup_prs = os.getenv("CLEANUP_PRS", "false").strip().lower() == "true"
    cleanup_packages = os.getenv("CLEANUP_PACKAGES", "false").strip().lower() == "true"

    artifact_pattern = os.getenv("ARTIFACT_NAME_PATTERN", "").strip() or "*"
    artifact_stale = os.getenv("ARTIFACT_STALE_DAYS", "30").strip()
    artifact_keep = os.getenv("ARTIFACT_KEEP_COUNT", "0").strip()

    pr_head_ref_pattern = os.getenv("PR_HEAD_REF_PATTERN", "").strip() or "*"
    pkg_name_pattern = os.getenv("PKG_NAME_PATTERN", "").strip() or "*"
    pkg_type = os.getenv("PKG_TYPE", "container").strip().lower() or "container"

    return {
        "branches": {
            "stale_days": int(branch_stale) if str(branch_stale).strip() else 45,
            "exclude_regex": exclude_regex_str,
            "exclude_regex_compiled": exclude_regex_compiled,
            "include_pattern": branch_include_pattern,
            "protect_pr": os.getenv("BRANCH_PROTECT_PR", "true").strip().lower() == "true",
        },
        "prs": {
            "stale_days": int(pr_stale) if str(pr_stale).strip() else 30,
            "exclude_labels": exclude_labels,
            "head_ref_pattern": pr_head_ref_pattern,
        },
        "packages": {
            "keep_versions": int(pkg_keep) if str(pkg_keep).strip() else 5,
            "name_pattern": pkg_name_pattern,
            "package_type": pkg_type,
        },
        "artifacts": {
            "name_pattern": artifact_pattern,
            "stale_days": int(artifact_stale) if str(artifact_stale).strip() else 30,
            "keep_count": int(artifact_keep) if str(artifact_keep).strip() else 0,
        },
        "cleanup_branches": cleanup_branches,
        "cleanup_artifacts": cleanup_artifacts,
        "cleanup_prs": cleanup_prs,
        "cleanup_packages": cleanup_packages,
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
    """ROLE: Service. INTENT: Track GitHub API rate limit from headers; wait when low; respect Retry-After.
    INPUT: min_remaining (optional). OUTPUT: N/A. SIDE_EFFECTS: time.sleep when throttled."""
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
                _log(f"[DBG-920] Rate limit low ({self._remaining} remaining); waiting {wait}s until reset")
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
                    if method == "DELETE":
                        return {}
                    return json.loads(body) if body else {}
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
                    _log(f"[DBG-921] API rate limit ({code}); retry in {wait}s (attempt {attempt + 1}/{RateLimiter.MAX_RETRIES})")
                    time.sleep(wait)
                    continue
                _log(f"[DBG-922] API Error: {e}")
                return None
            except Exception as e:
                last_error = e
                _log(f"[DBG-922] API Error: {e}")
                return None
        if last_error:
            _log(f"[DBG-923] API Error (max retries): {last_error}")
        return None

    def list_artifacts(self, owner: str, repo: str) -> list[dict]:
        """List all artifacts for a repo (paginated)."""
        out: list[dict] = []
        page = 1
        per_page = 100
        while True:
            url = (
                f"https://api.github.com/repos/{owner}/{repo}/actions/artifacts"
                f"?per_page={per_page}&page={page}"
            )
            data = self.request(url)
            if not data or not isinstance(data, dict):
                break
            artifacts = data.get("artifacts") or []
            out.extend(artifacts)
            if len(artifacts) < per_page:
                break
            page += 1
        return out

    def delete_artifact(self, owner: str, repo: str, artifact_id: int) -> bool:
        """Delete one artifact. Returns True if request succeeded (204)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/artifacts/{artifact_id}"
        result = self.request(url, method="DELETE")
        return result is not None

    def delete_branch(self, owner: str, repo: str, branch: str) -> bool:
        """Delete branch ref. Returns True if 204."""
        ref = f"heads/{branch}"
        url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/{ref}"
        result = self.request(url, method="DELETE")
        return result is not None

    def list_pulls(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        """List pull requests (paginated)."""
        out: list[dict] = []
        page = 1
        per_page = 100
        while True:
            url = (
                f"https://api.github.com/repos/{owner}/{repo}/pulls"
                f"?state={state}&per_page={per_page}&page={page}"
            )
            data = self.request(url)
            if not data or not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return out

    def close_issue(self, owner: str, repo: str, issue_number: int) -> bool:
        """Close an issue/PR. Returns True if request succeeded."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        result = self.request(url, method="PATCH", data={"state": "closed"})
        return result is not None and isinstance(result, dict)

    def list_org_packages(self, org: str, package_type: str = "container") -> list[dict]:
        """List packages for an organization (paginated)."""
        out: list[dict] = []
        page = 1
        per_page = 100
        while True:
            url = (
                f"https://api.github.com/orgs/{quote(org)}/packages"
                f"?package_type={package_type}&per_page={per_page}&page={page}"
            )
            data = self.request(url)
            if not data or not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return out

    def list_package_versions(self, org: str, package_type: str, package_name: str) -> list[dict]:
        """List versions for a package. package_name may need to be URL-encoded."""
        out: list[dict] = []
        page = 1
        per_page = 100
        while True:
            url = (
                f"https://api.github.com/orgs/{quote(org)}/packages/{package_type}/{quote(package_name, safe='')}/versions"
                f"?per_page={per_page}&page={page}"
            )
            data = self.request(url)
            if not data or not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return out

    def delete_package_version(self, org: str, package_type: str, package_name: str, version_id: int) -> bool:
        """Delete a package version. Returns True if request succeeded (204)."""
        url = f"https://api.github.com/orgs/{quote(org)}/packages/{package_type}/{quote(package_name, safe='')}/versions/{version_id}"
        result = self.request(url, method="DELETE")
        return result is not None


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
                _log("[DBG-910] Error: SCOPE=repo requires REPO to be set")
                raise SystemExit(1)
            if "/" not in spec and not org:
                _log("[DBG-911] Error: SCOPE=repo with REPO as name requires ORG_NAME (or use owner/repo)")
                raise SystemExit(1)
            result.append(_parse_repo_spec(spec, org or ""))

        elif scope == SCOPE_REPOS:
            reps = self._config.get("repos", [])
            if not reps:
                _log("[DBG-912] Error: SCOPE=repos requires REPOS to be set (comma or newline separated)")
                raise SystemExit(1)
            if any("/" not in s for s in reps) and not org:
                _log("[DBG-913] Error: SCOPE=repos with repo names (no owner/) requires ORG_NAME")
                raise SystemExit(1)
            for spec in reps:
                result.append(_parse_repo_spec(spec, org or ""))

        elif scope == SCOPE_TOPIC:
            topic = self._config.get("repo_topic", "").strip()
            if not topic or not org:
                _log("[DBG-914] Error: SCOPE=topic requires ORG_NAME and REPO_TOPIC (or TOPIC) to be set")
                raise SystemExit(1)
            q = f"org:{org} topic:{topic}"
            url = f"https://api.github.com/search/repositories?q={quote(q)}&per_page=100"
            data = self._client.request(url)
            if not data or not isinstance(data, dict):
                _log("[DBG-915] Error: Could not search repos by topic")
                raise SystemExit(1)
            for r in data.get("items", []):
                full = r.get("full_name", "")
                if full and "/" in full:
                    owner, repo_name = full.split("/", 1)
                    result.append((owner, repo_name))

        else:
            if not org:
                _log("[DBG-916] Error: SCOPE=org requires ORG_NAME to be set")
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
                _log("[DBG-917] Error: Could not list org repos")
                raise SystemExit(1)

        return result


def _parse_created_at(created_str: str | None) -> datetime | None:
    """Parse GitHub API created_at into datetime (UTC)."""
    if not created_str:
        return None
    s = (created_str or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class JanitorBot:
    """Scans (and optionally cleans) stale branches/PRs/artifacts; uses GitHubApiClient for throttling and retries."""
    def __init__(self, config: dict, api_client: GitHubApiClient) -> None:
        self.config = config
        self._api = api_client
        self.report: dict = {"branches": [], "prs": [], "packages": [], "artifacts": []}

    def scan_branches(self, owner: str, repo: str, mode: str = "scan") -> None:
        rules = self.config["branches"]
        dry_run = self.config["dry_run"]
        url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
        branches = self._api.request(url)
        if not branches:
            return

        threshold = datetime.now(tz=timezone.utc) - timedelta(days=rules["stale_days"])
        regex = rules["exclude_regex_compiled"]
        include_pattern = rules.get("include_pattern") or "*"

        for b in branches:
            name = b["name"]
            if regex.match(name):
                continue
            if include_pattern and include_pattern != "*" and not fnmatch.fnmatch(name, include_pattern):
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
                if mode == "cleanup" and not dry_run and not b.get("protected", False):
                    if self._api.delete_branch(owner, repo, name):
                        _log(f"[DBG-003] Deleted branch: {name}")

    def process_artifacts(self, owner: str, repo: str, mode: str) -> None:
        """List artifacts, filter by name pattern and age/keep_count; report and optionally delete."""
        rules = self.config["artifacts"]
        pattern = rules["name_pattern"] or "*"
        stale_days = rules["stale_days"]
        keep_count = rules["keep_count"]
        threshold = datetime.now(tz=timezone.utc) - timedelta(days=stale_days)
        dry_run = self.config["dry_run"]

        all_artifacts = self._api.list_artifacts(owner, repo)
        # Filter by name (glob)
        matching = [a for a in all_artifacts if fnmatch.fnmatch((a.get("name") or ""), pattern)]
        # Parse created_at and sort newest first
        with_dates: list[tuple[dict, datetime]] = []
        for a in matching:
            dt = _parse_created_at(a.get("created_at"))
            if dt is not None:
                with_dates.append((a, dt))
        with_dates.sort(key=lambda x: x[1], reverse=True)

        to_delete: list[tuple[dict, int]] = []
        for i, (a, created) in enumerate(with_dates):
            if created >= threshold:
                continue
            if keep_count > 0 and i < keep_count:
                continue
            days = (datetime.now(tz=timezone.utc) - created).days
            to_delete.append((a, days))

        repo_label = f"{owner}/{repo}"
        for a, days in to_delete:
            self.report["artifacts"].append({
                "repo": repo_label,
                "id": a.get("id"),
                "name": a.get("name", ""),
                "size_bytes": a.get("size_in_bytes", 0),
                "days": days,
            })
            if mode == "cleanup" and not dry_run:
                aid = a.get("id")
                if aid is not None:
                    if self._api.delete_artifact(owner, repo, int(aid)):
                        _log(f"[DBG-004] Deleted artifact: {a.get('name')} (id={aid})")
                    else:
                        _log(f"[DBG-924] Failed to delete artifact: {a.get('name')} (id={aid})")
            elif mode == "cleanup" and dry_run:
                _log(f"[DBG-005] [dry-run] Would delete artifact: {a.get('name')} (id={a.get('id')}, {days}d old)")

    def process_prs(self, owner: str, repo: str, mode: str) -> None:
        """List open PRs, filter by stale_days, exclude_labels, and optional head ref pattern; report and optionally close."""
        rules = self.config["prs"]
        stale_days = rules["stale_days"]
        exclude_labels = set(rules["exclude_labels"])
        head_ref_pattern = rules.get("head_ref_pattern") or "*"
        threshold = datetime.now(tz=timezone.utc) - timedelta(days=stale_days)
        dry_run = self.config["dry_run"]

        pulls = self._api.list_pulls(owner, repo, state="open")
        repo_label = f"{owner}/{repo}"

        for pr in pulls:
            head_ref = (pr.get("head", {}) or {}).get("ref", "")
            if head_ref_pattern and head_ref_pattern != "*" and not fnmatch.fnmatch(head_ref, head_ref_pattern):
                continue
            pr_labels = {lb.get("name") for lb in (pr.get("labels") or []) if lb.get("name")}
            if exclude_labels and pr_labels & exclude_labels:
                continue
            created_str = pr.get("created_at")
            created = _parse_created_at(created_str)
            if not created or created >= threshold:
                continue
            days = (datetime.now(tz=timezone.utc) - created).days
            pr_number = pr.get("number")
            title = (pr.get("title") or "")[:80]
            self.report["prs"].append({
                "repo": repo_label,
                "number": pr_number,
                "title": title,
                "head_ref": head_ref,
                "days": days,
            })
            if mode == "cleanup" and not dry_run:
                if self._api.close_issue(owner, repo, pr_number):
                    _log(f"[DBG-006] Closed PR #{pr_number}: {title}")
                else:
                    _log(f"[DBG-925] Failed to close PR #{pr_number}")
            elif mode == "cleanup" and dry_run:
                _log(f"[DBG-007] [dry-run] Would close PR #{pr_number}: {title} (head={head_ref}, {days}d old)")

    def process_packages(self, org: str, mode: str) -> None:
        """List org packages, filter by name pattern; for each package keep keep_count newest versions, report and delete older."""
        rules = self.config["packages"]
        name_pattern = rules.get("name_pattern") or "*"
        keep_count = rules["keep_versions"]
        package_type = rules.get("package_type") or "container"
        dry_run = self.config["dry_run"]

        packages = self._api.list_org_packages(org, package_type)
        for pkg in packages:
            pkg_name = pkg.get("name") or ""
            if name_pattern and name_pattern != "*" and not fnmatch.fnmatch(pkg_name, name_pattern):
                continue
            versions = self._api.list_package_versions(org, package_type, pkg_name)
            with_dates: list[tuple[dict, datetime]] = []
            for v in versions:
                created = _parse_created_at(v.get("created_at"))
                if created is not None:
                    with_dates.append((v, created))
            with_dates.sort(key=lambda x: x[1], reverse=True)
            to_delete = with_dates[keep_count:] if keep_count > 0 else []
            for v, created in to_delete:
                days = (datetime.now(tz=timezone.utc) - created).days
                vid = v.get("id")
                self.report["packages"].append({
                    "org": org,
                    "package_type": package_type,
                    "name": pkg_name,
                    "version_id": vid,
                    "days": days,
                })
                if mode == "cleanup" and vid is not None and not dry_run:
                    if self._api.delete_package_version(org, package_type, pkg_name, int(vid)):
                        _log(f"[DBG-008] Deleted package version: {pkg_name} id={vid}")
                    else:
                        _log(f"[DBG-926] Failed to delete package version: {pkg_name} id={vid}")
                elif mode == "cleanup" and dry_run:
                    _log(f"[DBG-009] [dry-run] Would delete package version: {pkg_name} id={vid} ({days}d old)")

    def generate_report(self) -> None:
        """Write Markdown report; explicitly state the thresholds used for the scan."""
        cfg = self.config
        branch_days = cfg["branches"]["stale_days"]
        pr_days = cfg["prs"]["stale_days"]
        pkg_keep = cfg["packages"]["keep_versions"]
        exclude_regex = cfg["branches"]["exclude_regex"]
        exclude_labels = ", ".join(cfg["prs"]["exclude_labels"]) or "(none)"
        scope_desc = cfg.get("scope", SCOPE_ORG)
        cleanup_branches = cfg.get("cleanup_branches", True)
        cleanup_artifacts = cfg.get("cleanup_artifacts", False)
        cleanup_prs = cfg.get("cleanup_prs", False)
        cleanup_packages = cfg.get("cleanup_packages", False)
        branch_include = cfg["branches"].get("include_pattern") or "*"
        pr_head_pattern = cfg["prs"].get("head_ref_pattern") or "*"
        pkg_name_pattern = cfg["packages"].get("name_pattern") or "*"
        pkg_type = cfg["packages"].get("package_type") or "container"
        art_pattern = cfg["artifacts"]["name_pattern"]
        art_days = cfg["artifacts"]["stale_days"]
        art_keep = cfg["artifacts"]["keep_count"]

        with open("janitor_report.md", "w", encoding="utf-8") as f:
            f.write("# Janitor Bot Report\n\n")
            f.write("## Thresholds used for this scan\n\n")
            f.write("| Rule | Value |\n|------|-------|\n")
            f.write(f"| Scope | `{scope_desc}` |\n")
            f.write(f"| Cleanup branches | `{cleanup_branches}` |\n")
            f.write(f"| Cleanup artifacts | `{cleanup_artifacts}` |\n")
            f.write(f"| Cleanup PRs | `{cleanup_prs}` |\n")
            f.write(f"| Cleanup packages | `{cleanup_packages}` |\n")
            f.write(f"| Branch stale (days) | `{branch_days}` |\n")
            f.write(f"| Branch exclude regex | `{exclude_regex}` |\n")
            f.write(f"| Branch include pattern | `{branch_include}` |\n")
            f.write("| Protected branches | **never touched** |\n")
            f.write(f"| PR stale (days) | `{pr_days}` |\n")
            f.write(f"| PR exclude labels | `{exclude_labels}` |\n")
            f.write(f"| PR head ref pattern | `{pr_head_pattern}` |\n")
            f.write(f"| Package versions to keep | `{pkg_keep}` |\n")
            f.write(f"| Package name pattern | `{pkg_name_pattern}` |\n")
            f.write(f"| Package type | `{pkg_type}` |\n")
            f.write(f"| Artifact name pattern | `{art_pattern}` |\n")
            f.write(f"| Artifact stale (days) | `{art_days}` |\n")
            f.write(f"| Artifact keep count | `{art_keep}` |\n")
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

            if self.report["artifacts"]:
                f.write("## Artifacts (stale / deleted)\n\n")
                f.write("| Repo | Artifact name | ID | Size (bytes) | Days stale |\n")
                f.write("|------|---------------|-----|--------------|------------|\n")
                for a in self.report["artifacts"]:
                    f.write(f"| {a['repo']} | {a['name']} | {a['id']} | {a['size_bytes']} | {a['days']} |\n")
                f.write("\n")
            else:
                f.write("## Artifacts\n\nNo matching stale artifacts found.\n\n")

            if self.report["prs"]:
                f.write("## Pull requests (stale / closed)\n\n")
                f.write("| Repo | PR | Title | Head ref | Days stale |\n")
                f.write("|------|-----|-------|----------|------------|\n")
                for p in self.report["prs"]:
                    f.write(f"| {p['repo']} | #{p['number']} | {p['title']} | {p['head_ref']} | {p['days']} |\n")
                f.write("\n")
            else:
                f.write("## Pull requests\n\nNo matching stale PRs found.\n\n")

            if self.report["packages"]:
                f.write("## Package versions (stale / deleted)\n\n")
                f.write("| Org | Type | Package | Version ID | Days stale |\n")
                f.write("|-----|------|---------|------------|------------|\n")
                for p in self.report["packages"]:
                    f.write(f"| {p['org']} | {p['package_type']} | {p['name']} | {p['version_id']} | {p['days']} |\n")
                f.write("\n")
            else:
                f.write("## Packages\n\nNo matching stale package versions found.\n\n")

        _log("[DBG-002] Report written to janitor_report.md")


class ScanRunner:
    """Runs branch and/or artifact scan over a list of repos with rate-limit awareness (batch-friendly)."""
    def __init__(self, bot: JanitorBot, config: dict, batch_delay_seconds: float = 0.0) -> None:
        self._bot = bot
        self._config = config
        self._batch_delay = max(0.0, batch_delay_seconds)

    def run(self, repos: list[tuple[str, str]], mode: str) -> None:
        for i, (owner, repo_name) in enumerate(repos):
            if self._config.get("cleanup_branches", True):
                self._bot.scan_branches(owner, repo_name, mode)
            if self._config.get("cleanup_artifacts", False):
                self._bot.process_artifacts(owner, repo_name, mode)
            if self._config.get("cleanup_prs", False):
                self._bot.process_prs(owner, repo_name, mode)
            if self._batch_delay > 0 and i < len(repos) - 1:
                time.sleep(self._batch_delay)
        # Packages are org-level: run once per unique owner
        if self._config.get("cleanup_packages", False) and repos:
            seen_owners: set[str] = set()
            for owner, _ in repos:
                if owner not in seen_owners:
                    seen_owners.add(owner)
                    self._bot.process_packages(owner, mode)
                    if self._batch_delay > 0:
                        time.sleep(self._batch_delay)


def main() -> None:
    """INTENT: Parse args, load config, run scan or cleanup. INPUT: None (argv). OUTPUT: None. SIDE_EFFECTS: Network, disk, stdout."""
    _log("[DBG-000] Starting Janitor Bot...")
    parser = argparse.ArgumentParser(description="Janitor Bot: scan or cleanup stale branches/PRs")
    parser.add_argument("--mode", choices=["scan", "cleanup"], required=True)
    args = parser.parse_args()

    config = get_config()
    if not config["token"]:
        _log("[DBG-918] Error: GH_TOKEN must be set (e.g. via workflow env)")
        raise SystemExit(1)
    scope = config.get("scope", SCOPE_ORG)
    if scope == SCOPE_ORG or scope == SCOPE_TOPIC:
        if not config["org"]:
            _log("[DBG-919] Error: ORG_NAME must be set for scope=org or scope=topic")
            raise SystemExit(1)
    elif scope == SCOPE_REPO and not config.get("repo"):
        if not config["org"]:
            _log("[DBG-919] Error: ORG_NAME or REPO must be set for scope=repo")
            raise SystemExit(1)
    elif scope == SCOPE_REPOS and not config.get("repos"):
        if not config["org"]:
            _log("[DBG-919] Error: ORG_NAME (default owner) or REPOS must be set for scope=repos")
            raise SystemExit(1)

    rate_limiter = RateLimiter()
    api_client = GitHubApiClient(config["token"], rate_limiter)
    resolver = RepoResolver(config, api_client)
    bot = JanitorBot(config, api_client)
    repos_to_scan = resolver.get_repos()

    batch_delay_str = os.getenv("BATCH_DELAY_SECONDS", "0.1").strip()
    try:
        batch_delay = float(batch_delay_str) if batch_delay_str else 0.0
    except ValueError:
        batch_delay = 0.0
    runner = ScanRunner(bot, config, batch_delay_seconds=batch_delay)
    runner.run(repos_to_scan, args.mode)

    if args.mode == "scan":
        bot.generate_report()
    _log("[DBG-001] Janitor Bot completed.")


if __name__ == "__main__":
    main()
