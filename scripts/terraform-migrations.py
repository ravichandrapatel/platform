#!/usr/bin/env python3
"""
FILE_NAME: terraform-migrations.py
DESCRIPTION: Migrate Terraform for_each configuration to workspace-based configuration:
  backup state, extract resources by repo key, transform state (module path and index_key),
  create/select workspace, push state, verify with plan, optional cleanup of old state.
VERSION: 1.2.0
EXIT_CODES: 0 = success, 1 = error (preflight, init, backup, transform, push, verify, or cleanup)
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_PREFIX = "[TF-MIGRATE]"

# DBG breadcrumbs (Golden Rules 1.6): [DBG-000] start; [DBG-001]..[DBG-019] flow; [DBG-9xx] errors/warnings.
# 0xx: 000 start, 001 dry-run, 002-003 preflight, 004-005 init, 006 backup, 007-008 resources, 009-010 transform,
#      011 workspace, 012-013 push, 014 verify, 015-016 cleanup/summary. 9xx: 910 prereq, 914 skip/no-resources,
#      921 re-init, 922 tf failure, 923 lock retry, 924-925 state replace, 926 version, 927 backend, 928-930 partial.

# Symbols for scan-friendly output
SYM_OK = "\u2713"      # ✓
SYM_WARN = "\u26a0\ufe0f"  # ⚠
SYM_ERR = "\u2717"     # ✗
SYM_STEP = "\u2192"    # →
SYM_INFO = "\u2139\ufe0f"  # ℹ


def _log(message: str, color: Optional[str] = None, code: Optional[str] = None) -> None:
    """INTENT: Print a message with the project prefix and optional [DBG-NNN] breadcrumb. INPUT: message (str), optional color, optional code. OUTPUT: None. SIDE_EFFECTS: stdout."""
    if code:
        message = f"{message} [{code}]"
    c = color or ""
    nc = "\033[0m" if c else ""
    print(f"{PROJECT_PREFIX} {c}{message}{nc}")


class Colors:
    """ROLE: Data. INTENT: ANSI color codes for CLI output."""
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def _log_header(message: str) -> None:
    """INTENT: Print a section header. INPUT: message (str). OUTPUT: None. SIDE_EFFECTS: stdout."""
    _log(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")
    _log(f"{Colors.BLUE}{message}{Colors.NC}")
    _log(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")


def _log_step(message: str, code: Optional[str] = None) -> None:
    """INTENT: Print a step message with optional [DBG-NNN]. INPUT: message (str), optional code. OUTPUT: None. SIDE_EFFECTS: stdout."""
    _log(f"{SYM_STEP} {message}", Colors.GREEN, code)


def _log_warning(message: str, code: Optional[str] = None) -> None:
    """INTENT: Print a warning with optional [DBG-NNN]. INPUT: message (str), optional code. OUTPUT: None. SIDE_EFFECTS: stdout."""
    _log(f"{SYM_WARN} {message}", Colors.YELLOW, code)


def _log_error(message: str, code: Optional[str] = None) -> None:
    """INTENT: Print an error with optional [DBG-NNN]. INPUT: message (str), optional code. OUTPUT: None. SIDE_EFFECTS: stdout."""
    _log(f"{SYM_ERR} {message}", Colors.RED, code)


def _log_success(message: str, code: Optional[str] = None) -> None:
    """INTENT: Print a success message with optional [DBG-NNN]. INPUT: message (str), optional code. OUTPUT: None. SIDE_EFFECTS: stdout."""
    _log(f"{SYM_OK} {message}", Colors.GREEN, code)


def run_command(
    command: List[str],
    cwd: Optional[str] = None,
    capture_output: bool = True,
) -> Tuple[int, str, str]:
    """INTENT: Run a subprocess; return (returncode, stdout, stderr). INPUT: command (list), cwd, capture_output. OUTPUT: Tuple[int, str, str]. SIDE_EFFECTS: subprocess."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=False,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return result.returncode, out, err
    except Exception as e:
        return -1, "", str(e)


def get_terraform_version() -> Optional[Tuple[int, int]]:
    """INTENT: Parse Terraform version (major, minor) from 'terraform version'. INPUT: None. OUTPUT: (major, minor) or None. SIDE_EFFECTS: subprocess."""
    return_code, stdout, _ = run_command(["terraform", "version"], cwd=None)
    if return_code != 0:
        return None
    match = re.search(r"Terraform v(\d+)\.(\d+)", stdout or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def check_terraform_version(min_major: int = 1, min_minor: int = 5) -> bool:
    """INTENT: Warn if Terraform version is below min (e.g. 1.5 for workspace improvements). INPUT: min_major, min_minor. OUTPUT: bool (True = ok or unknown). SIDE_EFFECTS: stdout."""
    ver = get_terraform_version()
    if ver is None:
        return True
    major, minor = ver
    if major < min_major or (major == min_major and minor < min_minor):
        _log_warning(f"Terraform {major}.{minor} detected; 1.5+ recommended for workspace behavior.", "DBG-926")
    return True


def get_backend_fingerprint(work_dir: Path) -> Optional[Dict[str, Any]]:
    """INTENT: Read backend config from .terraform/terraform.tfstate if present. INPUT: work_dir (Path). OUTPUT: backend dict or None. SIDE_EFFECTS: disk read."""
    tfstate = work_dir / ".terraform" / "terraform.tfstate"
    if not tfstate.exists():
        return None
    try:
        data = json.loads(tfstate.read_text())
        return data.get("backend")
    except (json.JSONDecodeError, OSError):
        return None


def check_backend_consistency(old_dir: Path, new_dir: Path) -> bool:
    """INTENT: Ensure old and new dirs use same backend type/config to avoid push failures. INPUT: old_dir, new_dir (Path). OUTPUT: bool. SIDE_EFFECTS: stdout."""
    old_backend = get_backend_fingerprint(old_dir)
    new_backend = get_backend_fingerprint(new_dir)
    if old_backend is None or new_backend is None:
        return True
    old_type = old_backend.get("type")
    new_type = new_backend.get("type")
    if old_type != new_type:
        _log_error(
            f"Backend mismatch: old={old_type!r} vs new={new_type!r}. "
            "State push may fail; ensure both dirs use the same backend.",
            "DBG-927",
        )
        return False
    old_config = old_backend.get("config") or {}
    new_config = new_backend.get("config") or {}
    for key in ("bucket", "key", "region", "dynamodb_table"):
        if old_config.get(key) != new_config.get(key):
            _log_warning("Backend config differs (e.g. key/prefix); old and new may point to different state.", "DBG-927")
            break
    return True


def check_prerequisites() -> bool:
    """INTENT: Ensure required CLI tools (terraform, aws) are on PATH. INPUT: None. OUTPUT: bool. SIDE_EFFECTS: None."""
    required = ["terraform", "aws"]
    missing = []
    for tool in required:
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        _log_error(f"Missing required tools: {', '.join(missing)}. Install them and try again.", "DBG-910")
        return False
    return True


def terraform_init(directory: Path) -> bool:
    """INTENT: Run terraform init in directory; skip if .terraform already populated. INPUT: directory (Path). OUTPUT: bool. SIDE_EFFECTS: subprocess, disk."""
    tf_dir = directory / ".terraform"
    if tf_dir.exists() and any(tf_dir.iterdir()):
        _log_step(f"Skipping terraform init in {directory} (already initialized)", "DBG-004")
        return True
    _log_step(f"Running terraform init in {directory}", "DBG-004")
    return_code, stdout, stderr = run_command(["terraform", "init", "-input=false"], cwd=str(directory))
    if return_code != 0:
        _log_error(f"terraform init failed in {directory}:\n{stderr}", "DBG-922")
        return False
    _log_success(f"terraform init completed in {directory}", "DBG-004")
    return True


def backup_state(old_dir: Path, repo_key: str, timestamp: str, dry_run: bool) -> Optional[Path]:
    """INTENT: Pull state from old_dir and write to backups/backup-{repo_key}-{timestamp}.json. INPUT: old_dir, repo_key, timestamp, dry_run. OUTPUT: Path or None. SIDE_EFFECTS: disk, subprocess."""
    if dry_run:
        _log(f"{SYM_INFO} [DRY RUN] Would back up state to backups/backup-{repo_key}-{timestamp}.json", code="DBG-006")
        return None
    backup_dir = old_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_file = backup_dir / f"backup-{repo_key}-{timestamp}.json"
    return_code, stdout, stderr = run_command(["terraform", "state", "pull"], cwd=str(old_dir))
    if return_code != 0:
        _log_error(f"terraform state pull failed in {old_dir}:\n{stderr}", "DBG-922")
        return None
    backup_file.write_text(stdout)
    if backup_file.stat().st_size == 0:
        _log_error("Backup file is empty", "DBG-922")
        return None
    _log_success(f"Backed up state to {backup_file}", "DBG-006")
    return backup_file


def get_resources_for_key(old_dir: Path, repo_key: str) -> List[str]:
    """INTENT: List state addresses that contain repo_key (for_each key); use re.escape for special chars. INPUT: old_dir (Path), repo_key (str). OUTPUT: List[str]. SIDE_EFFECTS: subprocess."""
    return_code, stdout, stderr = run_command(["terraform", "state", "list"], cwd=str(old_dir))
    if return_code != 0:
        _log_error(f"terraform state list failed in {old_dir}:\n{stderr}", "DBG-922")
        return []
    resources: List[str] = []
    pattern = re.compile(rf'\["{re.escape(repo_key)}"\]')
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if pattern.search(line):
            resources.append(line)
    return resources


def _normalize_state_address(addr: str) -> str:
    """INTENT: Normalize state address so state-list and JSON formats match (e.g. quote escaping). INPUT: addr (str). OUTPUT: str. SIDE_EFFECTS: None."""
    # Normalization avoids false "partial match / N requested resources not in transformed state" when
    # terraform state list and state pull use slightly different address strings for the same resource.
    if not addr:
        return addr
    return addr.replace('\\"', '"').strip()


def extract_and_transform_state(
    old_state: Dict[str, Any],
    repo_key: str,
    resource_addrs: List[str],
    log_skipped: bool = True,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """INTENT: Build new state with module path [repo_key] replaced by [0]; return state, included addrs, skipped (non-matching) addrs. INPUT: old_state, repo_key, resource_addrs, log_skipped. OUTPUT: (state_dict, included_addresses, skipped_addresses). SIDE_EFFECTS: optional logging."""
    new_resources: List[Dict[str, Any]] = []
    seen_addresses: set[str] = set()
    included_addresses: List[str] = []
    skipped_for_log: List[str] = []
    search_pattern = f'["{repo_key}"]'
    for resource in old_state.get("resources", []):
        res_mod = resource.get("module", "")
        res_type = resource.get("type", "")
        res_name = resource.get("name", "")
        old_addr = f"{res_mod}.{res_type}.{res_name}" if res_mod else f"{res_type}.{res_name}"
        res_mod_normalized = _normalize_state_address(res_mod)
        if search_pattern not in res_mod and search_pattern not in res_mod_normalized:
            skipped_for_log.append(old_addr)
            continue
        new_mod_path = res_mod.replace(search_pattern, "[0]")
        new_addr = f"{new_mod_path}.{res_type}.{res_name}"
        if new_addr in seen_addresses:
            continue
        instances = resource.get("instances", [])
        new_instances = []
        for instance in instances:
            new_inst = dict(instance)
            idx = instance.get("index_key")
            if str(idx) == repo_key:
                new_inst["index_key"] = 0
            # Keep "private" (provider metadata/checksums); stripping can trigger unnecessary recreations.
            new_instances.append(new_inst)
        if not new_instances:
            continue
        new_resource = dict(resource)
        new_resource["instances"] = new_instances
        new_resource["module"] = new_mod_path
        new_resource.pop("each", None)
        new_resources.append(new_resource)
        seen_addresses.add(new_addr)
        included_addresses.append(old_addr)
    if log_skipped and skipped_for_log:
        _log_warning(f"Skipped {len(skipped_for_log)} resource(s) (module does not match key {repo_key!r})", "DBG-928")
        for addr in skipped_for_log[:5]:
            _log(f"  {addr}", code="DBG-928")
        if len(skipped_for_log) > 5:
            _log(f"  ... and {len(skipped_for_log) - 5} more", code="DBG-928")
    new_state = {
        "version": 4,
        "terraform_version": old_state.get("terraform_version", ""),
        "serial": 1,
        "lineage": old_state.get("lineage"),
        "resources": new_resources,
    }
    requested_set = set(resource_addrs)
    included_set = set(included_addresses)
    normalized_included = {_normalize_state_address(a) for a in included_addresses}
    missing = [
        r for r in resource_addrs
        if _normalize_state_address(r) not in normalized_included
    ]
    return (new_state, included_addresses, list(missing))


def create_or_select_workspace(new_dir: Path, workspace: str, dry_run: bool) -> bool:
    """INTENT: Create workspace if missing, else select; re-init after. INPUT: new_dir (Path), workspace (str), dry_run (bool). OUTPUT: bool. SIDE_EFFECTS: subprocess."""
    if dry_run:
        _log(f"{SYM_INFO} [DRY RUN] Would create/select workspace {workspace}", code="DBG-011")
        return True
    return_code, stdout, stderr = run_command(["terraform", "workspace", "list"], cwd=str(new_dir))
    if return_code != 0:
        _log_error(f"terraform workspace list failed in {new_dir}:\n{stderr}", "DBG-922")
        return False
    workspace_exists = any(workspace in line for line in stdout.split("\n"))
    if workspace_exists:
        _log_step("Workspace exists, selecting...", "DBG-011")
        return_code, _, stderr = run_command(["terraform", "workspace", "select", workspace], cwd=str(new_dir))
    else:
        _log_step("Creating new workspace...", "DBG-011")
        return_code, _, stderr = run_command(["terraform", "workspace", "new", workspace], cwd=str(new_dir))
    if return_code != 0:
        _log_error(f"Failed to create/select workspace: {stderr}", "DBG-922")
        return False
    _log_step("Re-initializing after workspace change", "DBG-011")
    if not terraform_init(new_dir):
        _log_warning("Re-initialization after workspace change failed", "DBG-921")
    return True


def workspace_has_state(work_dir: Path) -> bool:
    """INTENT: Return True if the current workspace already has state (non-empty state list). INPUT: work_dir (Path). OUTPUT: bool. SIDE_EFFECTS: subprocess."""
    return workspace_state_count(work_dir) > 0


def workspace_state_count(work_dir: Path) -> int:
    """INTENT: Return number of resources in current workspace state (0 on error). INPUT: work_dir (Path). OUTPUT: int. SIDE_EFFECTS: subprocess."""
    return_code, stdout, _ = run_command(["terraform", "state", "list"], cwd=str(work_dir))
    if return_code != 0:
        return 0
    return len([line for line in stdout.strip().split("\n") if line.strip()])


def _is_state_lock_error(stderr: str) -> bool:
    """INTENT: Detect state lock / backend lock errors (e.g. DynamoDB PutItem, plan lock). INPUT: stderr (str). OUTPUT: bool. SIDE_EFFECTS: None."""
    lower = (stderr or "").lower()
    patterns = [
        r"lock",
        r"state is locked",
        r"putitem",
        r"conditional.*check.*failed",
        r"resourcecontention",
        r"transactionconflict",
    ]
    return any(re.search(p, lower) for p in patterns)


def push_state(
    new_dir: Path,
    state_file: Path,
    dry_run: bool,
    max_lock_retries: int = 5,
    lock_retry_delays: Optional[List[float]] = None,
) -> Tuple[bool, List[str]]:
    """INTENT: Push state file into new_dir with retries on state lock; return success and list of state addresses. INPUT: new_dir, state_file, dry_run, max_lock_retries, lock_retry_delays. OUTPUT: (bool, List[str]). SIDE_EFFECTS: subprocess."""
    if dry_run:
        _log(f"{SYM_INFO} [DRY RUN] Would push state to {new_dir}", code="DBG-012")
        return True, []
    delays = lock_retry_delays or [5.0, 10.0, 20.0, 30.0, 45.0]
    for attempt in range(max_lock_retries):
        return_code, stdout, stderr = run_command(
            ["terraform", "state", "push", str(state_file)],
            cwd=str(new_dir),
        )
        if return_code == 0:
            return_code, list_out, stderr = run_command(
                ["terraform", "state", "list"],
                cwd=str(new_dir),
            )
            if return_code != 0:
                return True, []
            lines = [line.strip() for line in list_out.split("\n") if line.strip()]
            return True, lines
        if _is_state_lock_error(stderr) and attempt < max_lock_retries - 1:
            wait = delays[attempt] if attempt < len(delays) else delays[-1]
            _log_warning(
                f"State lock/backend conflict (attempt {attempt + 1}/{max_lock_retries}); retrying in {wait:.0f}s...",
                "DBG-923",
            )
            _log(f"  {stderr[:300]}", code="DBG-923")
            time.sleep(wait)
            continue
        _log_error(f"terraform state push failed in {new_dir}:\n{stderr}", "DBG-922")
        return False, []
    _log_error("terraform state push failed after lock retries", "DBG-922")
    return False, []


def find_tfvars_for_key(new_dir: Path, repo_key: str) -> Optional[str]:
    """INTENT: Find a tfvars file in new_dir or its subdirs named {repo_key}.tfvars when --tfvars-file not provided. INPUT: new_dir (Path), repo_key (str). OUTPUT: Path as str or None. SIDE_EFFECTS: disk read."""
    if not repo_key or "/" in repo_key or "\\" in repo_key:
        return None
    name = f"{repo_key}.tfvars"
    p = new_dir / name
    if p.exists() and p.is_file():
        return str(p)
    for path in new_dir.rglob(name):
        if path.is_file():
            return str(path)
    return None


def verify_migrations(new_dir: Path, tfvars_file: Optional[str], dry_run: bool) -> bool:
    """INTENT: Run terraform plan -detailed-exitcode; 0 = no changes (success), 2 = changes (failure). INPUT: new_dir, tfvars_file, dry_run. OUTPUT: bool. SIDE_EFFECTS: subprocess."""
    if dry_run:
        _log(f"{SYM_INFO} [DRY RUN] Would verify migrations in {new_dir}", code="DBG-014")
        return True
    cmd: List[str] = ["terraform", "plan", "-detailed-exitcode", "-input=false"]
    if tfvars_file:
        cmd.extend(["-var-file", tfvars_file])
    _log_step("Running terraform plan...", "DBG-014")
    return_code, stdout, stderr = run_command(cmd, cwd=str(new_dir))
    if return_code == 0:
        _log_success("Plan shows no changes - migration successful", "DBG-014")
        return True
    if return_code == 2:
        _log_warning("Plan shows changes - migration may be incomplete", "DBG-914")
        _log(stdout or stderr, code="DBG-914")
        _log(
            f"  {SYM_INFO} Run 'terraform plan' in this workspace to see if changes are refresh-only (e.g. tags) or actual recreations.",
            code="DBG-914",
        )
        return False
    _log_error("Plan failed", "DBG-922")
    _log(stderr or stdout, code="DBG-922")
    return False


def remove_from_old_state(old_dir: Path, resources: List[str], dry_run: bool) -> bool:
    """INTENT: Run terraform state rm for each resource in old_dir. INPUT: old_dir (Path), resources (List[str]), dry_run (bool). OUTPUT: bool. SIDE_EFFECTS: subprocess."""
    if dry_run:
        _log(f"{SYM_INFO} [DRY RUN] Would remove resources from old state", code="DBG-015")
        return True
    for resource in resources:
        _log_step(f"Removing {resource} from old state...", "DBG-015")
        return_code, _, stderr = run_command(["terraform", "state", "rm", resource], cwd=str(old_dir))
        if return_code != 0:
            _log_error(f"terraform state rm failed for {resource}:\n{stderr}", "DBG-922")
            return False
    _log_success("Removed resources from old state", "DBG-015")
    return True


def main() -> int:
    """INTENT: Parse args, run migration steps (preflight, init, backup, transform, workspace, push, verify, cleanup). OUTPUT: exit code. SIDE_EFFECTS: disk, subprocess, stdout."""
    _log(f"{SYM_STEP} Starting migration (for_each \u2192 workspace)", code="DBG-000")
    parser = argparse.ArgumentParser(
        description="Migrate Terraform for_each configuration to workspace-based configuration",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--old-dir", type=Path, required=True, help="Path to the old Terraform directory")
    parser.add_argument("--new-dir", type=Path, required=True, help="Path to the new Terraform directory")
    parser.add_argument(
        "--repo-key",
        type=str,
        required=True,
        help="Repository key(s) to migrate; comma-separated for multiple (e.g. key1,key2,key3)",
    )
    parser.add_argument(
        "--tfvars-file",
        type=str,
        default=None,
        help="TFVars file(s) for verification; comma-separated for multiple (one per repo-key, or single for all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry run; no changes")
    parser.add_argument("--skip-verification", action="store_true", help="Skip terraform plan verification")
    parser.add_argument("--auto-cleanup", action="store_true", help="Remove migrated resources from old state")
    parser.add_argument(
        "--force-replace-state",
        action="store_true",
        help="If workspace already has state, replace it with pushed state (default: fail when state exists)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Push even if some requested resources were not matched (partial transform)",
    )
    parser.add_argument(
        "--max-lock-retries",
        type=int,
        default=5,
        metavar="N",
        help="Max retries for state lock/backend conflicts (default: 5)",
    )
    parser.add_argument(
        "--lock-delays",
        nargs="+",
        type=float,
        default=[5.0, 10.0, 20.0, 30.0, 45.0],
        metavar="SEC",
        help="Backoff delays (seconds) between lock retries (default: 5 10 20 30 45)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Process keys in parallel (reserved for future use; currently always serial)",
    )
    parser.add_argument(
        "--backup-per-key",
        action="store_true",
        help="Backup state before each key (use when state mutates mid-run with multiple keys)",
    )
    args = parser.parse_args()

    repo_keys = [k.strip() for k in args.repo_key.split(",") if k.strip()]
    if not repo_keys:
        _log_error("No repo key(s) provided (--repo-key)", "DBG-910")
        return 1

    tfvars_list: List[str] = []
    if args.tfvars_file:
        tfvars_list = [f.strip() for f in args.tfvars_file.split(",") if f.strip()]
        if tfvars_list and len(tfvars_list) != 1 and len(tfvars_list) != len(repo_keys):
            _log_error(
                f"Number of tfvars files ({len(tfvars_list)}) must be 1 (use for all keys) or equal to number of repo keys ({len(repo_keys)}).",
                "DBG-910",
            )
            return 1

    old_dir = Path(args.old_dir).resolve()
    new_dir = Path(args.new_dir).resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    _log_header(
        f"Migrating for_each -> workspace for {len(repo_keys)} key(s): {', '.join(repo_keys)}"
    )

    if args.dry_run:
        _log_warning("Dry run enabled. No changes will be made.", "DBG-001")

    _log(f"\n{SYM_INFO} Configuration: old={old_dir}, new={new_dir}, keys={', '.join(repo_keys)}", code="DBG-002")
    if tfvars_list:
        _log(f"  tfvars: {', '.join(tfvars_list)} (one per key)" if len(tfvars_list) == len(repo_keys) else f"  tfvars: {tfvars_list[0]} (shared)", code="DBG-002")

    _log_step("Step 1: Preflight checks", "DBG-002")
    if not old_dir.exists():
        _log_error(f"Old directory does not exist: {old_dir}", "DBG-910")
        return 1
    if not new_dir.exists():
        _log_error(f"New directory does not exist: {new_dir}", "DBG-910")
        return 1
    if not check_prerequisites():
        return 1
    check_terraform_version(min_major=1, min_minor=5)
    _log_success("Preflight checks completed", "DBG-003")

    _log_step("Initializing old directory...", "DBG-004")
    if not terraform_init(old_dir):
        _log_error("Failed to initialize old directory", "DBG-922")
        return 1
    _log_step("Initializing new directory...", "DBG-005")
    if not terraform_init(new_dir):
        _log_error("Failed to initialize new directory", "DBG-922")
        return 1
    if not check_backend_consistency(old_dir, new_dir):
        return 1

    # Step 2: Backup (once for full state, or per-key if requested)
    _log_step("Step 2: Backup old state", "DBG-006")
    backup_file: Optional[Path] = None
    if not args.backup_per_key:
        backup_label = "all" if len(repo_keys) > 1 else repo_keys[0]
        backup_file = backup_state(old_dir, backup_label, timestamp, args.dry_run)

    migrated: List[Tuple[str, List[str], Optional[Path]]] = []

    # Parallel stub: --parallel reserved; future impl could use concurrent.futures + threading.Lock for backend.
    if getattr(args, "parallel", False) and len(repo_keys) > 1:
        _log_step("Parallel mode reserved (future: concurrent.futures + locks); processing keys serially", "DBG-002")

    for key_index, repo_key in enumerate(repo_keys):
        _log_header(f"Key {key_index + 1}/{len(repo_keys)}: {repo_key}")

        # Step 3: Identify resources (from current state; after cleanup previous keys are gone)
        _log_step(f"Step 3: Identify resources for {repo_key}", "DBG-007")
        resources = get_resources_for_key(old_dir, repo_key)
        if not resources:
            _log_warning(f"No resources found for {repo_key}; skipping", "DBG-914")
            if key_index == 0:
                return_code, stdout, _ = run_command(
                    ["terraform", "state", "list"], cwd=str(old_dir)
                )
                if return_code == 0:
                    _log(f"  {SYM_INFO} Available keys in state:", code="DBG-914")
                    keys_set: set[str] = set()
                    for line in stdout.strip().split("\n"):
                        if '["' in line and '"]' in line:
                            try:
                                k = line.split('["')[1].split('"]')[0]
                                keys_set.add(k)
                            except IndexError:
                                pass
                    for k in sorted(keys_set):
                        _log(f"    {k}", code="DBG-914")
            continue

        _log_success(f"Found {len(resources)} resource(s) for {repo_key}", "DBG-008")
        if len(resources) <= 5:
            for res in resources:
                _log(f"    {res}", code="DBG-008")

        # Optional per-key backup
        if args.backup_per_key and not args.dry_run:
            backup_file = backup_state(old_dir, repo_key, timestamp, args.dry_run)

        # Step 4: Extract and transform state (pull current state each time)
        _log_step("Step 4: Extract and transform state", "DBG-009")
        transformed_state_file: Optional[Path] = None
        if not args.dry_run:
            return_code, stdout, stderr = run_command(
                ["terraform", "state", "pull"], cwd=str(old_dir)
            )
            if return_code != 0:
                _log_error("Failed to pull state", "DBG-922")
                return 1
            old_state = json.loads(stdout)
            new_state, included_addresses, missing_addresses = extract_and_transform_state(
                old_state, repo_key, resources, log_skipped=True
            )
            if missing_addresses and not args.force:
                _log_error(
                    f"Partial match: {len(missing_addresses)} requested resource(s) not in transformed state. Use --force to push anyway.",
                    "DBG-929",
                )
                for addr in missing_addresses[:5]:
                    _log(f"    {addr}", code="DBG-929")
                if len(missing_addresses) > 5:
                    _log(f"    ... and {len(missing_addresses) - 5} more", code="DBG-929")
                return 1
            if missing_addresses and args.force:
                _log_warning(f"Pushing with partial match ({len(missing_addresses)} not matched) (--force)", "DBG-930")
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                f.write(json.dumps(new_state, indent=2))
                transformed_state_file = Path(f.name)
            _log_success("Transformed state ready", "DBG-010")
        else:
            _log(f"{SYM_INFO} [DRY RUN] Would extract and transform state", code="DBG-010")

        _log_step("Step 5: Create/select workspace", "DBG-011")
        if not create_or_select_workspace(new_dir, repo_key, args.dry_run):
            return 1

        _log_step("Step 6: Push transformed state", "DBG-012")
        if not args.dry_run and transformed_state_file and transformed_state_file.exists():
            if workspace_has_state(new_dir) and not args.force_replace_state:
                _log_error(
                    f"Workspace '{repo_key}' already has state. Use --force-replace-state to overwrite.",
                    "DBG-924",
                )
                return 1
            if workspace_has_state(new_dir) and args.force_replace_state:
                n = workspace_state_count(new_dir)
                _log_warning(
                    f"Workspace has {n} resource(s); replacing will overwrite them (previous state orphaned in backend). (--force-replace-state)",
                    "DBG-925",
                )
            ok, workspace_resources = push_state(
                new_dir,
                transformed_state_file,
                False,
                max_lock_retries=args.max_lock_retries,
                lock_retry_delays=args.lock_delays,
            )
            if not ok:
                transformed_state_file.unlink(missing_ok=True)
                return 1
            transformed_state_file.unlink(missing_ok=True)
            _log_success(f"Pushed {len(workspace_resources)} resource(s) to workspace {repo_key}", "DBG-013")
            migrated.append((repo_key, resources, None))
        else:
            _log(f"{SYM_INFO} [DRY RUN] Would push transformed state", code="DBG-013")
            migrated.append((repo_key, resources, None))

        _log_step("Step 7: Verify migrations", "DBG-014")
        if not args.skip_verification:
            tfvars_for_key: Optional[str] = None
            if tfvars_list:
                tfvars_for_key = tfvars_list[key_index] if len(tfvars_list) == len(repo_keys) else tfvars_list[0]
            if tfvars_for_key is None:
                tfvars_for_key = find_tfvars_for_key(new_dir, repo_key)
                if tfvars_for_key:
                    _log(f"  {SYM_INFO} Using tfvars from new dir: {tfvars_for_key}", code="DBG-014")
            if not verify_migrations(new_dir, tfvars_for_key, args.dry_run):
                _log_error("Verification failed", "DBG-922")
                return 1
        else:
            _log(f"  {SYM_INFO} Skipping verification", code="DBG-014")

        if args.auto_cleanup:
            _log_step("Removing resources from old state (--auto-cleanup)", "DBG-015")
            if not remove_from_old_state(old_dir, resources, args.dry_run):
                return 1
        else:
            _log_warning("Manual cleanup required. To remove from old state:", "DBG-016")
            _log(f"  cd {old_dir}", code="DBG-016")
            for resource in resources:
                _log(f"  terraform state rm {resource}", code="DBG-016")
        _log("")

    if not migrated:
        _log_error("No keys were migrated (no resources found for any key)", "DBG-914")
        return 1

    # Summary
    _log_header("Migration completed")
    if args.backup_per_key:
        _log(f"  {SYM_OK} Backed up per-key in {old_dir}/backups/", code="DBG-016")
    else:
        _log(f"  {SYM_OK} Backed up: {backup_file}", code="DBG-016")
    total_resources = sum(len(r) for _, r, _ in migrated)
    _log(f"  {SYM_OK} {total_resources} resource(s) across {len(migrated)} workspace(s)", code="DBG-016")
    for repo_key, res_list, _ in migrated:
        _log(f"    {repo_key}: {len(res_list)} resources", code="DBG-016")
    _log(f"\n  {SYM_INFO} To use: terraform workspace select <name> then plan/apply", code="DBG-016")
    _log_success("Migration completed successfully", "DBG-016")
    return 0


if __name__ == "__main__":
    sys.exit(main())
