# Terraform Migrations Script

Migrate Terraform **for_each** configuration to **workspace-based** configuration: backup state, extract resources by repo key, transform state (module path and `index_key`), create/select workspaces, push state, verify with `terraform plan`, and optionally remove migrated resources from the old state.

**Version:** 1.2.0  
**Requirements:** Python 3.9+, `terraform`, `aws` CLI on `PATH`. Terraform 1.5+ recommended.

---

## Quick start

```bash
./terraform-migrations.py \
  --old-dir /path/to/old-tf \
  --new-dir /path/to/new-tf \
  --repo-key my-repo
```

---

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--old-dir` | Path to the **old** Terraform directory (for_each state) | *(required)* |
| `--new-dir` | Path to the **new** Terraform directory (workspace-based) | *(required)* |
| `--repo-key` | Repository key(s) to migrate; **comma-separated** for multiple | *(required)* |
| `--tfvars-file` | TFVars file(s) for verification; **comma-separated** = one per repo-key, or single = shared | — |
| `--dry-run` | Show what would be done; no changes | `false` |
| `--skip-verification` | Skip `terraform plan` after push | `false` |
| `--auto-cleanup` | Remove migrated resources from old state after push | `false` |
| `--force-replace-state` | Overwrite workspace state if it already has resources | `false` |
| `--force` | Push even if some requested resources were not matched (partial transform) | `false` |
| `--max-lock-retries` | Max retries for state lock / backend conflicts | `5` |
| `--lock-delays` | Backoff delays in seconds between retries | `5 10 20 30 45` |
| `--parallel` | Reserved for future parallel mode; currently ignored (serial only) | `false` |
| `--backup-per-key` | Backup state **before each key** (use when state mutates with multiple keys) | `false` |

---

## Usage scenarios

### 1. Single repo key (one workspace)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app
```

- Backs up old state to `tf-old/backups/backup-my-app-<timestamp>.json`
- Creates/selects workspace `my-app` in `tf-new`
- Pushes transformed state and runs `terraform plan` for verification

---

### 2. Multiple repo keys (multiple workspaces)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "repo-a,repo-b,repo-c"
```

- One full backup at start: `backups/backup-all-<timestamp>.json`
- Processes each key in order: backup → transform → workspace → push → verify → optional cleanup
- After each key, if `--auto-cleanup` is set, resources are removed from old state before the next key

---

### 3. Dry run (no changes)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --dry-run
```

- Validates paths, init, and backend consistency
- Logs what would be backed up, transformed, pushed, and cleaned up; no state or files modified

---

### 4. Use tfvars for verification

**No `--tfvars-file` (auto-detect when verification runs):**

If you omit `--tfvars-file` and do **not** use `--skip-verification`, the script looks in the **new** directory and its **subdirectories** for a file named `{repo-key}.tfvars` and uses it for `terraform plan` if found:

- `{repo-key}.tfvars`

Example: for `--repo-key my-app`, it checks `new-dir/my-app.tfvars` then any subdir (e.g. `new-dir/envs/prod/my-app.tfvars`). If found, verification runs with that file and a log line like “Using tfvars from new dir: …” is printed. If not found, plan runs without `-var-file`.

**Single key (one tfvars):**

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --tfvars-file production.tfvars
```

- Runs `terraform plan -var-file=production.tfvars` after push to verify no unwanted changes.

**Multiple keys with one shared tfvars:**

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "repo-a,repo-b,repo-c" \
  --tfvars-file production.tfvars
```

- The same tfvars file is used for verification after each key.

**Multiple keys with one tfvars per key:**

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "repo-a,repo-b,repo-c" \
  --tfvars-file "repo-a.tfvars,repo-b.tfvars,repo-c.tfvars"
```

- Verification uses `repo-a.tfvars` for workspace `repo-a`, `repo-b.tfvars` for `repo-b`, and `repo-c.tfvars` for `repo-c`. The number of tfvars files must be **1** (shared) or **equal** to the number of repo keys.

---

### 5. Auto-remove from old state

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "repo-a,repo-b" \
  --auto-cleanup
```

- After each key is pushed and verified, runs `terraform state rm <resource>` in the **old** directory for that key’s resources
- Use when you are confident the new workspace state is correct and you want to avoid manual cleanup

---

### 6. Workspace already has state (overwrite)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --force-replace-state
```

- If the target workspace already has state, the script normally exits with an error
- `--force-replace-state` overwrites that state with the pushed state (previous state is orphaned in the backend)

---

### 7. Partial transform (some resources not matched)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --force
```

- If some requested resource addresses are not found in the transformed state, the script normally exits
- `--force` allows pushing the partial state and logs a warning

---

### 8. State lock / backend retries

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --max-lock-retries 8 \
  --lock-delays 5 10 15 20 30 40 50 60
```

- On state lock or backend errors (e.g. DynamoDB PutItem), the script retries with backoff
- Adjust retries and delays for slow or contended backends

---

### 9. Backup before each key (multi-key safety)

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "key1,key2,key3" \
  --backup-per-key
```

- Backs up state **before** processing each key (in `tf-old/backups/`)
- Useful when `--auto-cleanup` is used and state changes between keys

---

### 10. Skip plan verification

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key my-app \
  --skip-verification
```

- Pushes state but does **not** run `terraform plan`
- Use only when you will run plan/apply yourself

---

### 11. Repo key with special characters

Keys like `my-repo-v1.2` are supported; the script uses `re.escape` so dots and hyphens are matched literally in state addresses.

```bash
./terraform-migrations.py \
  --old-dir ./tf-old \
  --new-dir ./tf-new \
  --repo-key "my-repo-v1.2"
```

---

## Address matching (state list)

The script compares resources from `terraform state list` with the transformed state. To avoid false "partial match: N requested resources not in transformed state" messages, it:

- Builds **one address per instance** in the same format as `terraform state list`: with index suffix `[0]`, `[1]`, or `["key"]` for count/for_each resources.
- Uses the **data.** prefix for data sources (e.g. `data.github_team.team["xxx"]`).
- **Normalizes** address strings (e.g. quote escaping) so differences between state list and state JSON do not cause mismatches.

If you still see a partial match, the requested state list may include resources whose module path does not contain the given repo key, or addresses that differ in another way; use `--force` only when you intend to push a subset.

---

## Exit codes

| Code | Meaning |
|------|--------|
| `0` | Success |
| `1` | Error (preflight, init, backup, transform, push, verify, or cleanup) |

---

## Output and logs

- All lines are prefixed with `[TF-MIGRATE]` and use symbols: ✓ success, ⚠ warning, ✗ error, → step, ℹ info.
- Breadcrumb codes `[DBG-NNN]` follow the project logging standard for traceability.

---

## After migration

Use the new workspace:

```bash
cd <new-dir>
terraform workspace select <repo-key>
terraform plan          # or terraform plan -var-file=<tfvars>
terraform apply         # or terraform apply -var-file=<tfvars>
```

If verification reported plan changes (exit code 2), run `terraform plan` in the workspace to see whether changes are refresh-only (e.g. tags) or actual recreations.

---

## Tests

From the script directory:

```bash
python3 -m unittest test_terraform_migrations -v
```
