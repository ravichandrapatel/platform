#!/usr/bin/env python3
"""
FILE_NAME: drift_auditor.py
DESCRIPTION: Detects infrastructure drift across many Terraform workspaces (single S3 backend)
  using parallel terraform plan -json. Zero-dependency (stdlib only). ProcessPoolExecutor
  with isolated symlink-mirror workers; writes one GitHub Issue "Infrastructure Drift Report" per repo.
VERSION: 1.0.0
EXIT_CODES: 0 = clean, 1 = error (config), 2 = drift detected
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.request

# Pause API calls when remaining rate limit is at or below this (avoid 403 in logs)
RATE_LIMIT_PAUSE_THRESHOLD = 10

PREFIX = "[DRIFT-AUDIT]"
DRIFT_ISSUE_TITLE = "Infrastructure Drift Report"


def _log(msg: str) -> None:
    """INTENT: Emit a prefixed log line to stdout. INPUT: msg (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    print(f"{PREFIX} {msg}")


# ---------------------------------------------------------------------------
# GitHub API (stdlib only)
# ---------------------------------------------------------------------------

class GitHubApiError(Exception):
    """ROLE: Data. INTENT: Represent a 4xx GitHub API error. INPUT: code (int), body (str). OUTPUT: N/A. SIDE_EFFECTS: None."""

    def __init__(self, code: int, body: str) -> None:
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


class GitHubApiClient:
    """ROLE: Service. INTENT: Minimal GitHub REST API client (stdlib urllib). INPUT: token, api_url. OUTPUT: N/A. SIDE_EFFECTS: Network I/O."""

    def __init__(self, token: str, api_url: Optional[str] = None) -> None:
        self._token = token.strip()
        base = (api_url or os.getenv("GITHUB_API_URL", "https://api.github.com")).rstrip("/")
        self._base_url = base

    def _request(
        self, method: str, path: str, data: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "drift-auditor",
        }
        body_bytes = None
        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                # API resilience: pause before hitting rate limit (cleaner than 403 in logs)
                try:
                    remaining = resp.headers.get("X-RateLimit-Remaining")
                    if remaining is not None:
                        left = int(remaining)
                        if left <= RATE_LIMIT_PAUSE_THRESHOLD:
                            reset_ts = resp.headers.get("X-RateLimit-Reset")
                            if reset_ts:
                                wait = max(0, int(reset_ts) - int(time.time()))
                                wait = min(wait, 300)
                                if wait > 0:
                                    _log(f"[DBG-920] Rate limit low ({left} left); pausing {wait}s until reset.")
                                    time.sleep(wait)
                            else:
                                time.sleep(60)
                except (ValueError, TypeError):
                    pass
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            if 400 <= e.code < 500:
                raise GitHubApiError(e.code, body) from e
            return None

    def list_issues(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            path = f"/repos/{owner}/{repo}/issues?state={state}&per_page=100&page={page}"
            data = self._request("GET", path)
            if not isinstance(data, list):
                break
            out.extend(data)
            if len(data) < 100:
                break
            page += 1
        return out

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> Optional[Dict[str, Any]]:
        return self._request("POST", f"/repos/{owner}/{repo}/issues", {"title": title, "body": body})

    def update_issue(self, owner: str, repo: str, issue_number: int, body: str) -> Optional[Dict[str, Any]]:
        return self._request("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", {"body": body})

    def close_issue(self, owner: str, repo: str, issue_number: int) -> Optional[Dict[str, Any]]:
        return self._request("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", {"state": "closed"})


# ---------------------------------------------------------------------------
# Worker isolation: symlink-mirror of working_dir (exclude .terraform)
# ---------------------------------------------------------------------------

def _mirror_dir(src: str, dest: str, exclude: Set[str]) -> None:
    """INTENT: Create dest dir structure and symlink files from src; skip dirs in exclude.
    INPUT: src (str), dest (str), exclude (Set[str]). OUTPUT: None. SIDE_EFFECTS: Disk (mkdir, symlink)."""
    src_path = Path(src).resolve()
    dest_path = Path(dest).resolve()
    for root, dirs, files in os.walk(src_path):
        rel = Path(root).relative_to(src_path)
        dest_dir = dest_path / rel
        dest_dir.mkdir(parents=True, exist_ok=True)
        for d in list(dirs):
            if d in exclude:
                dirs.remove(d)
        for f in files:
            src_file = Path(root) / f
            dest_file = dest_dir / f
            if not dest_file.exists():
                dest_file.symlink_to(src_file.resolve())


def _make_worker_dir(working_dir: str) -> str:
    """INTENT: Create temp dir with symlink-mirror of working_dir (exclude .terraform, .git).
    INPUT: working_dir (str). OUTPUT: Path (str). SIDE_EFFECTS: Disk (temp dir, symlinks)."""
    worker_dir = tempfile.mkdtemp(prefix="drift-worker-")
    _mirror_dir(working_dir, worker_dir, exclude={".terraform", ".git"})
    return worker_dir


# ---------------------------------------------------------------------------
# Plan JSON: scrub sensitive, extract resource changes
# ---------------------------------------------------------------------------

def _scrub_sensitive(obj: Any) -> Any:
    """INTENT: Recursively replace values with sibling 'sensitive': true by '[sensitive]'.
    INPUT: obj (Any). OUTPUT: Any (scrubbed copy). SIDE_EFFECTS: None."""
    if isinstance(obj, dict):
        if obj.get("sensitive") is True and "value" in obj:
            return "[sensitive]"
        return {k: _scrub_sensitive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_sensitive(v) for v in obj]
    return obj


def _extract_changes(plan_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """INTENT: From plan JSON get resource_changes (address, actions); scrub sensitive.
    INPUT: plan_json (Dict). OUTPUT: List[Dict]. SIDE_EFFECTS: None."""
    out: List[Dict[str, Any]] = []
    for rc in plan_json.get("resource_changes") or []:
        change = rc.get("change") or {}
        actions = change.get("actions") or []
        if not actions or actions == ["no-op"]:
            continue
        out.append({
            "address": rc.get("address", ""),
            "actions": actions,
            "change": _scrub_sensitive(change),
        })
    return out


# ---------------------------------------------------------------------------
# Expected drift (exclude patterns)
# ---------------------------------------------------------------------------

def _parse_exclude_patterns(value: Optional[str]) -> List[str]:
    """INTENT: Parse --exclude input (newline/comma or JSON array) into list of patterns.
    INPUT: value (Optional[str]). OUTPUT: List[str]. SIDE_EFFECTS: None."""
    if not value or not value.strip():
        return []
    raw = value.strip()
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            return [str(p).strip() for p in arr if str(p).strip()]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]


def _change_matches_exclude(workspace: str, address: str, pattern: str) -> bool:
    """INTENT: Return True if (workspace, address) matches pattern (substring or workspace:substring).
    INPUT: workspace (str), address (str), pattern (str). OUTPUT: bool. SIDE_EFFECTS: None."""
    if ":" in pattern:
        ws_prefix, addr_part = pattern.split(":", 1)
        if ws_prefix.strip() != workspace:
            return False
        return addr_part.strip() in address
    return pattern in address


def _apply_excludes(
    results: List[Tuple[str, int, List[Dict[str, Any]], Optional[str]]],
    exclude_patterns: List[str],
) -> Tuple[
    List[Tuple[str, int, List[Dict[str, Any]], Optional[str]]],
    List[Tuple[str, Dict[str, Any]]],
]:
    """
    INTENT: Filter out changes matching exclude patterns; return filtered results and excluded list.
    INPUT: results, exclude_patterns (List[str]). OUTPUT: (filtered_results, excluded_list). SIDE_EFFECTS: None.
    """
    if not exclude_patterns:
        return results, []

    filtered: List[Tuple[str, int, List[Dict[str, Any]], Optional[str]]] = []
    excluded: List[Tuple[str, Dict[str, Any]]] = []

    for ws, exitcode, changes, err in results:
        if exitcode != 2 or not changes:
            filtered.append((ws, exitcode, changes, err))
            continue
        included: List[Dict[str, Any]] = []
        for c in changes:
            addr = c.get("address", "")
            if any(_change_matches_exclude(ws, addr, p) for p in exclude_patterns):
                excluded.append((ws, c))
            else:
                included.append(c)
        if not included:
            filtered.append((ws, 0, [], err))
        else:
            filtered.append((ws, 2, included, err))

    return filtered, excluded


# ---------------------------------------------------------------------------
# Single-worker plan (runs in subprocess / isolated env)
# ---------------------------------------------------------------------------

def _run_plan_worker(
    workspace: str,
    tfvars_path: str,
    working_dir_source: str,
    plugin_cache_dir: str,
    var_file_relative_to_worker: str,
    backend_config_path: Optional[str],
    init_timeout: int,
    plan_timeout: int,
) -> Tuple[str, int, List[Dict[str, Any]], Optional[str]]:
    """
    INTENT: Run terraform init + workspace select + plan in isolated worker dir.
    INPUT: workspace, tfvars_path, working_dir_source, plugin_cache_dir, var_file_relative_to_worker, backend_config_path, init_timeout, plan_timeout.
    OUTPUT: Tuple[workspace, exitcode, changes, error_message]. exitcode: 0 clean, 1 error, 2 drift.
    SIDE_EFFECTS: Disk (worker dir), subprocess (terraform), network (providers).
    """
    # _log("[T-01] Creating worker dir")
    worker_dir = _make_worker_dir(working_dir_source)
    cwd = worker_dir
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = plugin_cache_dir
    env["TF_INPUT"] = "false"

    init_cmd: List[str] = ["terraform", "init", "-input=false"]
    if backend_config_path and os.path.isabs(backend_config_path):
        init_cmd.extend(["-backend-config", backend_config_path])
    elif backend_config_path:
        init_cmd.extend(["-backend-config", os.path.join(worker_dir, backend_config_path)])

    try:
        r = subprocess.run(
            init_cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=init_timeout,
            text=True,
        )
        if r.returncode != 0:
            # _log("[ERR-T-01] terraform init failed")
            return (workspace, 1, [], (r.stderr or r.stdout or "init failed")[:500])

        r = subprocess.run(
            ["terraform", "workspace", "select", workspace],
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=30,
            text=True,
        )
        if r.returncode != 0:
            return (workspace, 1, [], (r.stderr or "workspace select failed")[:500])

        plan_cmd = [
            "terraform", "plan",
            "-detailed-exitcode",
            "-json",
            "-lock=false",
            "-input=false",
            f"-var-file={var_file_relative_to_worker}",
        ]
        r = subprocess.run(
            plan_cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=plan_timeout,
            text=True,
        )
        out = r.stdout or ""
        err = (r.stderr or "").strip()

        if r.returncode == 0:
            return (workspace, 0, [], None)
        if r.returncode == 2:
            try:
                plan_data = json.loads(out)
                changes = _extract_changes(plan_data)
                return (workspace, 2, changes, None)
            except Exception as e:
                # _log("[ERR-T-02] plan JSON parse failed")
                return (workspace, 2, [], str(e))
        return (workspace, 1, [], (err or out or "plan failed")[:500])
    finally:
        # Remove only this worker's temp dir (sub-cache); shared plugin_cache_dir stays intact
        if worker_dir:
            try:
                shutil.rmtree(worker_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Discovery: tfvars -> workspaces; backend workspace list -> zombies
# ---------------------------------------------------------------------------

def discover_workspaces(vars_folder: str) -> List[Tuple[str, str]]:
    """INTENT: Return [(workspace_name, absolute_tfvars_path), ...] from vars_folder.
    INPUT: vars_folder (str). OUTPUT: List[Tuple[str, str]]. SIDE_EFFECTS: Disk (read dir)."""
    path = Path(vars_folder)
    if not path.is_dir():
        return []
    out: List[Tuple[str, str]] = []
    for f in path.glob("*.tfvars"):
        workspace = f.stem
        out.append((workspace, str(f.resolve())))
    return sorted(out, key=lambda x: x[0])


def get_backend_workspaces(
    working_dir: str,
    plugin_cache_dir: str,
    backend_config_path: Optional[str],
    init_timeout: int = 300,
) -> Set[str]:
    """INTENT: Run init + workspace list in temp dir; return set of backend workspace names.
    INPUT: working_dir, plugin_cache_dir, backend_config_path, init_timeout. OUTPUT: Set[str]. SIDE_EFFECTS: Disk, subprocess."""
    worker_dir: Optional[str] = None
    worker_dir = _make_worker_dir(working_dir)
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = plugin_cache_dir
    env["TF_INPUT"] = "false"
    init_cmd = ["terraform", "init", "-input=false"]
    if backend_config_path:
        init_cmd.extend(["-backend-config", backend_config_path])
    try:
        subprocess.run(init_cmd, cwd=worker_dir, env=env, capture_output=True, timeout=init_timeout, check=False)
        r = subprocess.run(
            ["terraform", "workspace", "list"],
            cwd=worker_dir,
            env=env,
            capture_output=True,
            timeout=30,
            text=True,
        )
        if r.returncode != 0:
            return set()
        names: Set[str] = set()
        for line in (r.stdout or "").splitlines():
            name = line.strip().lstrip("*").strip()
            if name:
                names.add(name)
        return names
    finally:
        # Remove only this worker's temp dir; shared plugin_cache_dir (root binaries) stays intact
        if worker_dir:
            try:
                shutil.rmtree(worker_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Report and GitHub Issue
# ---------------------------------------------------------------------------

def build_markdown(
    results: List[Tuple[str, int, List[Dict[str, Any]], Optional[str]]],
    zombie_workspaces: List[str],
    vars_folder: str,
    excluded: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
) -> str:
    """INTENT: Build single markdown report (summary, zombies, excluded, drift, errors).
    INPUT: results, zombie_workspaces, vars_folder, excluded. OUTPUT: str. SIDE_EFFECTS: None."""
    excluded = excluded or []
    lines = [
        "# Infrastructure Drift Report",
        "",
        f"**Vars folder:** `{vars_folder}`",
        "",
    ]
    # Summary
    drifted = [r for r in results if r[1] == 2]
    errors = [r for r in results if r[1] == 1]
    clean = [r for r in results if r[1] == 0]
    lines.extend([
        "## Summary",
        "",
        f"| Status | Count |",
        f"|--------|-------|",
        f"| Clean | {len(clean)} |",
        f"| Drift | {len(drifted)} |",
        f"| Error | {len(errors)} |",
        f"| Zombie state (no tfvars) | {len(zombie_workspaces)} |",
        "",
    ])
    if excluded:
        lines.append(f"**Excluded (expected drift):** {len(excluded)} change(s) not counted as drift.")
        lines.append("")
    if zombie_workspaces:
        lines.append("## Zombie workspaces (state in S3, no .tfvars)")
        lines.append("")
        if "default" in zombie_workspaces:
            lines.append("> **⚠️ Security / shadow-infra:** The `default` workspace has state in the backend but no `default.tfvars`. Many teams leave default empty; resources in default can be a security risk. Consider adding `default.tfvars` to audit it, or remove/empty the default workspace state.")
            lines.append("")
        for z in sorted(zombie_workspaces):
            lines.append(f"- `{z}`")
        lines.append("")
    if excluded:
        lines.append("## Excluded (expected) drift")
        lines.append("")
        lines.append("These changes match your exclude patterns and are not counted as drift.")
        lines.append("")
        lines.append("| Workspace | Resource | Actions |")
        lines.append("|-----------|----------|---------|")
        for ws, c in excluded:
            addr = c.get("address", "")
            actions = ",".join(c.get("actions") or [])
            lines.append(f"| {ws} | `{addr}` | {actions} |")
        lines.append("")
    if drifted:
        lines.append("## Drift by workspace")
        lines.append("")
        lines.append("| Workspace | Resource | Actions |")
        lines.append("|-----------|----------|---------|")
        for ws, _ec, changes, _err in drifted:
            for c in changes:
                addr = c.get("address", "")
                actions = ",".join(c.get("actions") or [])
                lines.append(f"| {ws} | `{addr}` | {actions} |")
        lines.append("")
    if errors:
        lines.append("## Errors")
        lines.append("")
        for ws, _ec, _ch, err in errors:
            lines.append(f"### {ws}")
            lines.append("")
            lines.append(f"```\n{(err or 'unknown')[:1000]}\n```")
            lines.append("")
    return "\n".join(lines)


def _split_repo(repo_spec: str, default_owner: str) -> Tuple[str, str]:
    if "/" in (repo_spec or ""):
        a, b = repo_spec.strip().split("/", 1)
        return a.strip(), b.strip()
    return default_owner.strip(), repo_spec.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    working_dir: str,
    vars_folder: str,
    max_parallel: int,
    plugin_cache_dir: str,
    backend_config_path: Optional[str],
    github_token: Optional[str],
    repo: Optional[str],
    init_timeout: int = 300,
    plan_timeout: int = 600,
    exclude_patterns: Optional[List[str]] = None,
) -> int:
    """
    Returns: 0 clean, 1 error, 2 drift.
    exclude_patterns: resource address substrings (or 'workspace:substring') to treat as expected drift.
    """
    working_dir_abs = str(Path(working_dir).resolve())
    vars_folder_abs = str(Path(working_dir_abs) / vars_folder.lstrip("/")) if not os.path.isabs(vars_folder) else vars_folder

    # _log("[T-01] Discovering workspaces from tfvars")
    _log("[DBG-001] Discovering workspaces from tfvars...")
    ws_tfvars = discover_workspaces(vars_folder_abs)
    tfvars_workspaces = {w for w, _ in ws_tfvars}
    if not ws_tfvars:
        _log("[DBG-910] No .tfvars found; nothing to plan.")
        return 0

    # _log("[T-02] Fetching backend workspace list")
    _log("[DBG-002] Fetching backend workspace list (for zombie detection)...")
    backend_workspaces = get_backend_workspaces(
        working_dir_abs, plugin_cache_dir, backend_config_path, init_timeout=init_timeout
    )
    zombie_workspaces = sorted(backend_workspaces - tfvars_workspaces)

    # Relative var-file path for each workspace (relative to worker dir root)
    # Worker dir is a mirror of working_dir_abs; tfvars are under vars_folder which is under working_dir.
    # So from worker root, var file is same relative path as from working_dir_abs.
    def rel_var_file(ws: str) -> str:
        for w, p in ws_tfvars:
            if w == ws:
                return str(Path(p).relative_to(working_dir_abs))
        return ""

    results: List[Tuple[str, int, List[Dict[str, Any]], Optional[str]]] = []
    # _log("[T-03] Running parallel plans")
    _log(f"[DBG-003] Running plan for {len(ws_tfvars)} workspaces (max_parallel={max_parallel})...")
    with ProcessPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                _run_plan_worker,
                ws,
                p,
                working_dir_abs,
                plugin_cache_dir,
                rel_var_file(ws),
                backend_config_path,
                init_timeout,
                plan_timeout,
            ): ws
            for ws, p in ws_tfvars
        }
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                # _log("[ERR-T-03] Worker exception")
                results.append((futures[fut], 1, [], str(e)))

    patterns = exclude_patterns or []
    if patterns:
        results, excluded_list = _apply_excludes(results, patterns)
        _log(f"[DBG-004] Excluded {len(excluded_list)} expected drift change(s) matching {len(patterns)} pattern(s).")
    else:
        excluded_list = []

    has_drift = any(r[1] == 2 for r in results)
    has_error = any(r[1] == 1 for r in results)

    report_body = build_markdown(results, zombie_workspaces, vars_folder, excluded=excluded_list)

    if github_token and repo:
        owner, repo_name = _split_repo(repo, os.getenv("GITHUB_REPOSITORY_OWNER", ""))
        if owner and repo_name:
            api = GitHubApiClient(github_token, os.getenv("GITHUB_API_URL"))
            issues = [i for i in api.list_issues(owner, repo_name, "open") if i.get("title") == DRIFT_ISSUE_TITLE]
            if has_drift or zombie_workspaces:
                body_with_footer = report_body + "\n\n---\n*Generated by Terraform Drift Auditor*"
                if issues:
                    api.update_issue(owner, repo_name, issues[0]["number"], body_with_footer)
                    _log("[DBG-005] Updated existing drift issue.")
                else:
                    api.create_issue(owner, repo_name, DRIFT_ISSUE_TITLE, body_with_footer)
                    _log("[DBG-006] Created drift issue.")
            elif issues:
                api.close_issue(owner, repo_name, issues[0]["number"])
                _log("[DBG-007] Drift resolved; closed drift issue.")

    # Write report to file for artifact (use GITHUB_WORKSPACE in CI if set)
    report_dir = os.getenv("GITHUB_WORKSPACE") or working_dir_abs
    report_path = Path(report_dir) / "drift-report.md"
    report_path.write_text(report_body, encoding="utf-8")
    _log(f"[DBG-002] Report written to {report_path}")

    if has_error:
        return 1
    if has_drift or zombie_workspaces:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Terraform Drift Auditor")
    parser.add_argument("--working-dir", default=".", help="Terraform working directory")
    parser.add_argument("--vars-folder", required=True, help="Folder containing *.tfvars (relative to working-dir)")
    parser.add_argument("--max-parallel", type=int, default=10, help="Max parallel plans")
    parser.add_argument("--plugin-cache-dir", default=None, help="TF_PLUGIN_CACHE_DIR (default: .tf-plugin-cache)")
    parser.add_argument("--backend-config", default=None, help="Path to backend config file")
    parser.add_argument("--init-timeout", type=int, default=300, help="Timeout in seconds for terraform init (default 300)")
    parser.add_argument("--plan-timeout", type=int, default=600, help="Timeout in seconds for terraform plan (default 600)")
    parser.add_argument("--github-token", default=None, help="Token for GitHub issue create/update")
    parser.add_argument("--repo", default=None, help="Owner/repo for drift issue")
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        dest="exclude",
        help="Expected drift: exclude changes whose resource address contains this (repeatable). Use 'workspace:substring' to scope. Also accepts JSON array in one value.",
    )
    args = parser.parse_args()

    exclude_patterns: List[str] = []
    if args.exclude:
        for v in args.exclude:
            exclude_patterns.extend(_parse_exclude_patterns(v))

    plugin_cache = (
        args.plugin_cache_dir
        or os.getenv("TF_PLUGIN_CACHE_DIR")
        or os.path.join(Path(args.working_dir).resolve(), ".tf-plugin-cache")
    )
    os.makedirs(plugin_cache, exist_ok=True)

    return run(
        working_dir=args.working_dir,
        vars_folder=args.vars_folder,
        max_parallel=max(1, min(args.max_parallel, 10)),
        plugin_cache_dir=os.path.abspath(plugin_cache),
        backend_config_path=args.backend_config,
        github_token=args.github_token or os.getenv("GITHUB_TOKEN"),
        repo=args.repo or os.getenv("GITHUB_REPOSITORY"),
        init_timeout=max(60, args.init_timeout),
        plan_timeout=max(120, args.plan_timeout),
        exclude_patterns=exclude_patterns,
    )


if __name__ == "__main__":
    sys.exit(main())
