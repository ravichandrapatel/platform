"""
FILE_NAME: main.py
DESCRIPTION: Path-filter between two Git refs: YAML groups with glob patterns (incl. **),
  "!" negation with last-match-wins. Outputs GITHUB_OUTPUT (has_changes, files, every_file_matches)
  and optional change-type filtering. Ref-agnostic; zero-SHA guard for new branches.
VERSION: 2.0.0
EXIT_CODES: 0 = success, 1 = error (config, git, or I/O)
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from wcmatch import glob as wc_glob

# Constants for exit codes
EXIT_CODE_SUCCESS = 0
EXIT_CODE_ERROR = 1

# Zero SHA (40 zeros) = new branch, nothing to diff against
ZERO_SHA = "0" * 40

PROJECT_PREFIX = "[GIT-PATH-FILTER]"
_debug = False


def _log(message: str) -> None:
    """INTENT: Print a message with the project prefix (breadcrumb/debug). INPUT: message (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    print(f"{PROJECT_PREFIX} {message}")


def parse_args() -> argparse.Namespace:
    """INTENT: Parse CLI (base-ref, source-ref, filter-spec, dry-run, change-types, debug).
    INPUT: None (argv).
    OUTPUT: argparse.Namespace.
    SIDE_EFFECTS: None."""
    p = argparse.ArgumentParser(
        description="Detect file changes between two refs using path-filter patterns (sequential, last-match-wins)."
    )
    p.add_argument("--base-ref", required=True, help="Base ref (branch, tag, or SHA); no origin/ prefix")
    p.add_argument("--source-ref", required=True, help="Source/head ref (branch, tag, or SHA)")
    p.add_argument(
        "--filter-spec",
        required=True,
        help="Path to YAML file or YAML string with filter mapping (key -> list of globs; ! = exclude)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print diff and match results to stdout; do not write GITHUB_OUTPUT",
    )
    p.add_argument(
        "--change-types",
        default="",
        help="Comma-separated status filter: A,M,D (e.g. A,M = only added/modified). Empty = all.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Log why each file was included or excluded per group",
    )
    p.add_argument(
        "--working-directory",
        default="",
        help="Base path for patterns; only paths under this dir are considered; matching uses paths relative to this dir",
    )
    return p.parse_args()


def load_filter_config(filter_spec: str) -> dict[str, list[str]]:
    """INTENT: Load filter config from YAML file or string (key -> list of glob patterns).
    INPUT: filter_spec (str) path or inline YAML.
    OUTPUT: Dict[str, List[str]].
    SIDE_EFFECTS: Disk read if file path."""
    # [T-01] Load YAML (file path or inline string)
    if os.path.exists(filter_spec):
        with open(filter_spec, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    else:
        data = yaml.safe_load(filter_spec)

    if not isinstance(data, dict):
        raise ValueError("filter spec must be a YAML mapping of key -> [patterns]")
    for k, v in list(data.items()):
        if v is None:
            data[k] = []
        elif not isinstance(v, list):
            data[k] = [str(v)]
        else:
            data[k] = [str(p) for p in v]
    _log(f"[DBG-001] Loaded {len(data)} filter groups: {', '.join(data.keys())}")
    return data


# wcmatch flags: GLOBSTAR for **, BRACE for {a,b}; paths matched as POSIX
_WC_FLAGS = wc_glob.GLOBSTAR | wc_glob.BRACE


def compile_patterns(patterns: list[str]) -> list[tuple[bool, str]]:
    """INTENT: Normalize glob strings to (negated, pattern_str); ! prefix = negation. Matching via wcmatch.
    INPUT: patterns (List[str]).
    OUTPUT: List of (negated: bool, pattern: str).
    SIDE_EFFECTS: None."""
    result: list[tuple[bool, str]] = []
    for p in patterns:
        if not isinstance(p, str):
            continue
        p = p.strip().lstrip("/")
        if not p:
            continue
        neg = p.startswith("!")
        if neg:
            p = p[1:].strip().lstrip("/")
        if not p:
            continue
        result.append((neg, p))
    return result


def run_git_cmd(args: list[str], ignore_error: bool = False, cwd: str | None = None) -> str:
    """INTENT: Run git command; return stdout. INPUT: args, optional ignore_error, cwd. OUTPUT: str. SIDE_EFFECTS: subprocess."""
    # [T-02] Execute git (list args, no shell)
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        return (result.stdout or "").strip()
    except subprocess.CalledProcessError as e:
        if ignore_error:
            _log(f"[DBG-920] Git command failed (ignoring): {(e.stderr or '').strip()}")
            return ""
        _log(f"[DBG-922] Git command failed: {(e.stderr or '').strip()}")
        raise


def fetch_ref(ref: str) -> None:
    """INTENT: Fetch a single ref from origin with depth=1, no tags (ref-agnostic). INPUT: ref (str). OUTPUT: None. SIDE_EFFECTS: subprocess."""
    # [T-03] git fetch origin <ref> --depth=1 --no-tags
    if len(ref) == 40 and ref == ZERO_SHA:
        return
    run_git_cmd(["git", "fetch", "origin", ref, "--depth=1", "--no-tags"], ignore_error=True)


def is_zero_sha(ref: str) -> bool:
    """INTENT: Detect zero SHA (new-branch push). INPUT: ref (str). OUTPUT: bool. SIDE_EFFECTS: None."""
    return ref.strip() == ZERO_SHA or (len(ref) == 40 and all(c == "0" for c in ref))


def get_changed_files_with_status(
    base_ref: str,
    source_ref: str,
) -> list[tuple[str, str]]:
    """INTENT: Return list of (status, path) between base and source; status A/M/D; paths POSIX.
    Zero-SHA base: list all files in source commit. INPUT: base_ref, source_ref. OUTPUT: List[(status, path)]. SIDE_EFFECTS: subprocess."""
    # [T-04] Fetch both refs (no origin/ prefix)
    fetch_ref(base_ref)
    fetch_ref(source_ref)

    if is_zero_sha(base_ref):
        # [T-05] New branch: list all files in source
        out = run_git_cmd(["git", "ls-tree", "-r", "--name-only", source_ref])
        if not out:
            return []
        return [("A", Path(p).as_posix()) for p in out.splitlines() if p.strip()]

    # [T-06] Diff with merge base for PR-style comparison; --name-status gives A/M/D
    out = run_git_cmd(
        ["git", "diff", "--name-status", "-z", f"{base_ref}...{source_ref}"],
        ignore_error=True,
    )
    if not out:
        out = run_git_cmd(
            ["git", "diff", "--name-status", "-z", base_ref, source_ref],
            ignore_error=True,
        )
    if not out:
        return []

    # Parse NUL-separated status+path (STATUS\tPATH\0...)
    pairs: list[tuple[str, str]] = []
    for part in out.split("\0"):
        part = part.strip()
        if not part or "\t" not in part:
            continue
        status, path = part.split("\t", 1)
        raw = (status or "M")[0]
        status_map = {"R": "R", "C": "C", "T": "M"}.get(raw, raw)
        if status_map not in "AMD":
            status_map = "M"
        pairs.append((status_map, Path(path.strip()).as_posix()))
    _log(f"[DBG-002] Found {len(pairs)} changed file(s) with status.")
    return pairs


def filter_by_change_types(
    status_paths: list[tuple[str, str]],
    allowed: set[str],
) -> list[str]:
    """INTENT: Keep only paths whose status is in allowed; return paths only. INPUT: status_paths, allowed. OUTPUT: List[str]. SIDE_EFFECTS: None."""
    if not allowed:
        return [p for _, p in status_paths]
    return [p for s, p in status_paths if s in allowed]


def match_file_sequential(path: str, compiled: list[tuple[bool, str]]) -> bool | None:
    """INTENT: Last-match-wins: iterate patterns; last matching pattern decides include (True) or exclude (False). No match -> None.
    INPUT: path (str, POSIX), compiled list of (negated, glob_str). OUTPUT: True=included, False=excluded, None=no match. SIDE_EFFECTS: None."""
    last: bool | None = None
    for neg, pat in compiled:
        if wc_glob.globmatch(path, pat, flags=_WC_FLAGS):
            last = not neg
    return last


def _path_for_match(path: str, working_directory: str) -> str:
    """INTENT: Return path relative to working_directory for pattern matching; POSIX.
    INPUT: path, working_directory (normalized, may be empty). OUTPUT: path str. SIDE_EFFECTS: None."""
    if not working_directory:
        return path
    wd = working_directory.rstrip("/")
    if path == wd or path.startswith(wd + "/"):
        return path[len(wd) :].lstrip("/") or "."
    return path


def process_changes(
    filter_config: dict[str, list[str]],
    changed_files: list[str],
    all_considered: set[str],
    debug: bool,
    working_directory: str = "",
) -> dict[str, Any]:
    """INTENT: Group changed files by filter keys (sequential, last-match-wins); add _unmatched and every_file_matches.
    INPUT: filter_config, changed_files, all_considered, debug, working_directory. OUTPUT: Dict. SIDE_EFFECTS: None."""
    output: dict[str, Any] = {}
    compiled_groups: dict[str, list[tuple[bool, str]]] = {}
    for key, patterns in filter_config.items():
        compiled_groups[key] = compile_patterns(patterns)

    wd = (working_directory or "").rstrip("/")
    all_matched: set[str] = set()
    considered_list = sorted(all_considered)

    for key, compiled in compiled_groups.items():
        matched: list[str] = []
        for path in considered_list:
            path_for_match = _path_for_match(path, working_directory)
            result = match_file_sequential(path_for_match, compiled)
            if result is True:
                matched.append(path)
                if debug:
                    _log(f"[DBG-003] [{key}] include: {path} (last match wins)")
            elif result is False and debug:
                _log(f"[DBG-003] [{key}] exclude: {path} (last match wins)")
        all_matched.update(matched)
        every = bool(all_considered and all_considered.issubset(set(matched)))
        output[key] = {
            "has_changes": bool(matched),
            "files": sorted(matched),
            "every_file_matches": every,
        }

    remaining = sorted(all_considered - all_matched)
    output["_unmatched"] = {
        "has_changes": bool(remaining),
        "files": remaining,
        "every_file_matches": False,
    }

    if remaining and debug:
        _log(f"[DBG-003] _unmatched: {remaining}")
    return output


def write_github_output(result: dict[str, Any], github_output_path: str) -> None:
    """INTENT: Append all outputs to GITHUB_OUTPUT using file-append; multiline values use delimiter.
    INPUT: result dict, github_output_path. OUTPUT: None. SIDE_EFFECTS: Writes to file."""
    # [T-07] GITHUB_OUTPUT file-append
    changed_keys = [k for k, v in result.items() if v.get("has_changes") and k != "_unmatched"]
    with open(github_output_path, "a", encoding="utf-8") as fh:
        fh.write(f"changes<<__CHANGES_EOF__\n{json.dumps(changed_keys)}\n__CHANGES_EOF__\n")
        fh.write(f"changes_json<<__JSON_EOF__\n{json.dumps(result, sort_keys=True)}\n__JSON_EOF__\n")
        for key, data in result.items():
            fh.write(f"{key}={str(data.get('has_changes', False)).lower()}\n")
            fh.write(f"{key}_files<<__FILES_{key}__\n{json.dumps(data.get('files', []))}\n__FILES_{key}__\n")
            fh.write(f"{key}_every_file_matches={str(data.get('every_file_matches', False)).lower()}\n")


def main() -> int:
    """INTENT: Load config, fetch refs, diff, match (sequential), write GITHUB_OUTPUT or dry-run print.
    INPUT: None. OUTPUT: int exit code. SIDE_EFFECTS: Disk, subprocess, env."""
    try:
        args = parse_args()
        global _debug
        _debug = args.debug
        _log("[DBG-000] Starting Git Path Filter...")

        # [T-01] Load filter config (YAML via PyYAML)
        filter_conf = load_filter_config(args.filter_spec)

        # [T-04–T-06] Git: fetch refs, get changed files with status
        status_paths = get_changed_files_with_status(args.base_ref.strip(), args.source_ref.strip())
        allowed_statuses: set[str] = set()
        if args.change_types:
            allowed_statuses = {s.strip().upper() for s in args.change_types.split(",") if s.strip()}
            if allowed_statuses and not allowed_statuses.issubset({"A", "M", "D"}):
                allowed_statuses = {"A", "M", "D"}
        changed_files = filter_by_change_types(status_paths, allowed_statuses)
        work_dir = Path(args.working_directory).as_posix().rstrip("/") if (args.working_directory or "").strip() else ""
        if work_dir:
            changed_files = [p for p in changed_files if p == work_dir or p.startswith(work_dir + "/")]
        all_considered = set(changed_files)

        # [T-07] Match (sequential, last-match-wins); patterns relative to working_directory
        result = process_changes(filter_conf, changed_files, all_considered, args.debug, work_dir)

        if args.dry_run:
            _log("[DBG-004] DRY RUN: diff and match results (paths POSIX)")
            print(json.dumps(result, indent=2, sort_keys=True))
            return EXIT_CODE_SUCCESS

        # Write GITHUB_OUTPUT only when not dry-run
        if "GITHUB_OUTPUT" in os.environ:
            write_github_output(result, os.environ["GITHUB_OUTPUT"])
        else:
            _log("[DBG-921] GITHUB_OUTPUT not set; skipping file-append.")

        _log(f"[DBG-002] Success: detected changes in {sum(1 for k, v in result.items() if v.get('has_changes'))} group(s).")
        return EXIT_CODE_SUCCESS

    except Exception as e:
        _log(f"[DBG-923] Unexpected error: {e}")
        return EXIT_CODE_ERROR


if __name__ == "__main__":
    sys.exit(main())
