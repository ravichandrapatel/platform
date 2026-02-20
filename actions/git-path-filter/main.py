"""git-change-detector main

This implements path-filter semantics similar to dorny/paths-filter:
- Filter spec is a YAML mapping of keys -> list of glob patterns.
- Patterns starting with "!" are exclusions (negations) applied to the key.
- Matching uses fnmatch semantics on POSIX-style paths (forward slashes).

The script writes `changes.json` with the structure:
  { key: {"has_changes": bool, "files": [list of files]} }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Any

import yaml

# Constants for exit codes
EXIT_CODE_SUCCESS = 0
EXIT_CODE_ERROR = 1

# Configure logging to show timestamps and levels
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    p = argparse.ArgumentParser(description="Detect file changes using path-filter style patterns.")
    p.add_argument("--base-ref", required=True, help="Base ref (e.g. main)")
    p.add_argument("--source-ref", required=True, help="Source/head ref (e.g. feature/foo)")
    p.add_argument("--filter-spec", required=True, help="Path to YAML file or YAML string with filter mapping")
    return p.parse_args()


def run_git_cmd(args: List[str], ignore_error: bool = False) -> str:
    """Helper to run git commands with logging and error handling."""
    cmd_str = " ".join(args)
    logger.info(f"Running git command: {cmd_str}")
    
    try:
        # Run command and capture output
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if ignore_error:
            logger.warning(f"Git command failed (ignoring): {e.stderr.strip()}")
            return ""
        logger.error(f"Git command failed: {e.stderr.strip()}")
        raise e


def load_filter_config(filter_spec: str) -> Dict[str, List[str]]:
    """Load the YAML filter configuration from a file or string."""
    logger.info("Loading filter configuration...")
    
    if os.path.exists(filter_spec):
        logger.info(f"Reading filter spec from file: {filter_spec}")
        with open(filter_spec, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    else:
        logger.info("Parsing filter spec from string input")
        data = yaml.safe_load(filter_spec)

    if not isinstance(data, dict):
        raise ValueError("filter spec must be a YAML mapping of key -> [patterns]")
    
    # Ensure every key has a list of patterns
    for k, v in list(data.items()):
        if v is None:
            data[k] = []
        elif not isinstance(v, list):
            data[k] = [str(v)]
            
    logger.info(f"Loaded {len(data)} filter groups: {', '.join(data.keys())}")
    return data


def fetch_refs(base_ref: str, source_ref: str) -> None:
    """Fetch the necessary git history to compare branches."""
    base_ref = base_ref.replace("origin/", "")
    source_ref = source_ref.replace("origin/", "")
    logger.info(f"Fetching history for '{base_ref}' and '{source_ref}'...")
    try:
        run_git_cmd(["git", "fetch", "--no-tags", "--prune", "origin", base_ref, source_ref])
    except subprocess.CalledProcessError:
        logger.warning("Standard fetch failed. Attempting fallback fetch...")
        run_git_cmd(
            ["git", "fetch", "origin", f"{base_ref}:refs/remotes/origin/{base_ref}", f"{source_ref}:refs/remotes/origin/{source_ref}"],
            ignore_error=True,
        )


def get_changed_files(base_ref: str, source_ref: str) -> List[str]:
    """Run git diff to find files changed between base and source."""
    base_ref = base_ref.replace("origin/", "")
    source_ref = source_ref.replace("origin/", "")
    # Prefer origin/ refs (standard fetch); fallback to local refs if diff fails (e.g. after fallback fetch)
    out = ""
    for base, src in [
        (f"origin/{base_ref}", f"origin/{source_ref}"),
        (base_ref, source_ref),
    ]:
        try:
            logger.info(f"Comparing {base}...{src}")
            out = run_git_cmd(["git", "diff", "--name-only", f"{base}...{src}"])
            break
        except subprocess.CalledProcessError:
            continue
    else:
        logger.error("git diff failed for both origin/ and local refs")
        raise RuntimeError("Could not diff refs")

    if not out:
        logger.info("No changed files found in git diff.")
        return []
    files = [Path(p).as_posix() for p in out.splitlines() if p.strip()]
    logger.info(f"Found {len(files)} changed file(s).")
    return files


def match_patterns_for_key(patterns: List[str], files: List[str]) -> List[str]:
    """
    Check which files match the given list of patterns.
    Handles '!' for exclusions (e.g., '!src/test/**').
    """
    matched: List[str] = []
    for pat in patterns:
        if not isinstance(pat, str):
            continue
        pat = pat.strip()
        if not pat:
            continue
            
        # Check if this is a negation pattern
        neg = pat.startswith("!")
        if neg:
            pat = pat[1:]
            
        # Normalize pattern to use forward slashes (POSIX)
        pat = pat.lstrip("/")
        
        if neg:
            # If negation, remove files that match this pattern
            matched = [f for f in matched if not fnmatch(f, pat)]
        else:
            # If normal pattern, add files that match
            for f in files:
                if fnmatch(f, pat) and f not in matched:
                    matched.append(f)
    return matched


def process_changes(filter_config: Dict[str, List[str]], changed_files: List[str]) -> Dict[str, Any]:
    """Group changed files based on the filter configuration."""
    output: Dict[str, Any] = {}
    all_matched = set()

    logger.info("Processing patterns against changed files...")

    for key, patterns in filter_config.items():
        matched = match_patterns_for_key(patterns, changed_files)
        
        # Log results for this key
        if matched:
            logger.info(f"  -> Group '{key}': {len(matched)} file(s) matched")
        
        output[key] = {"has_changes": bool(matched), "files": sorted(matched)}
        all_matched.update(matched)

    # Calculate files that didn't match any group
    remaining = [f for f in changed_files if f not in all_matched]
    if remaining:
        logger.info(f"  -> Unmatched: {len(remaining)} file(s)")
        
    output["_unmatched"] = {"has_changes": bool(remaining), "files": sorted(remaining)}

    return output


def main() -> int:
    try:
        args = parse_args()
        
        # 1. Load Configuration
        filter_conf = load_filter_config(args.filter_spec)

        # 2. Git Operations
        fetch_refs(args.base_ref, args.source_ref)
        changed = get_changed_files(args.base_ref, args.source_ref)

        # 3. Match Logic
        result = process_changes(filter_conf, changed)

        # 4. Output Results
        logger.info("Writing results to changes.json")
        with open("changes.json", "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)

        # 5. GitHub Actions Output
        if "GITHUB_OUTPUT" in os.environ:
            logger.info("Writing results to GITHUB_OUTPUT")
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                # Output list of changed keys
                changed_keys = [k for k, v in result.items() if v["has_changes"] and k != "_unmatched"]
                fh.write(f"changes={json.dumps(changed_keys)}\n")
                fh.write(f"changes_json={json.dumps(result)}\n")
                
                for key, data in result.items():
                    fh.write(f"{key}={str(data['has_changes']).lower()}\n")
                    fh.write(f"{key}_files={json.dumps(data['files'])}\n")

        # Summary
        total_keys = sum(1 for k in result if result[k].get("has_changes"))
        logger.info(f"Success! Detected changes in {total_keys} group(s).")
        return EXIT_CODE_SUCCESS

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return EXIT_CODE_ERROR


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)