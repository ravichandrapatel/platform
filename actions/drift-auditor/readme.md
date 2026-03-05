# Terraform Drift Auditor

Detects **infrastructure drift** across many Terraform workspaces (single S3 backend) by running `terraform plan` in parallel on one runner. No GitHub Actions strategy matrix—uses Python `ProcessPoolExecutor` with isolated worker dirs to avoid workspace collisions. Creates or updates a single GitHub Issue **"Infrastructure Drift Report"** per repo; auto-closes it when drift is resolved.

**Zero dependencies:** Python stdlib only (`urllib`, `json`, `subprocess`, `concurrent.futures`). No `requests`, `pandas`, or `yaml`.

---

## How it works

1. **Discovery** – Crawls `vars_folder` for `*.tfvars`; each file maps to a workspace (basename without `.tfvars`). Fetches backend workspace list via one `terraform init` + `terraform workspace list`; workspaces in S3 with no matching `.tfvars` are reported as **zombie state**.
2. **Parallel plans** – Up to 10 workers run `terraform plan -detailed-exitcode -json -lock=false -var-file=...` in isolated symlink-mirrors of your working dir (each has its own `.terraform` and workspace selection).
3. **Shared provider cache** – Uses `TF_PLUGIN_CACHE_DIR` so providers are downloaded once and reused.
4. **Drift report** – Parses plan JSON for `resource_changes` (address + actions), scrubs any values marked `sensitive: true`, and aggregates into one Markdown table.
5. **GitHub Issue** – One issue per repo titled **"Infrastructure Drift Report"**: created or updated when there is drift or zombies; closed when everything is clean and a previous issue existed.

---

## Prerequisites

- **Terraform** on `PATH` (the action uses `hashicorp/setup-terraform`).
- **Single S3 backend** with one state per workspace; the runner must have credentials to read state (e.g. AWS OIDC role or env vars).
- **Vars layout:** One `.tfvars` file per workspace under `vars_folder`; workspace name = filename without `.tfvars` (e.g. `envs/prod.tfvars` → workspace `prod`).

---

## Using the GitHub Action

Add the action to a workflow (e.g. cron or `workflow_dispatch`). Ensure the job has AWS credentials if your backend is S3.

### Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `working_dir` | No | `'.'` | Terraform root (e.g. `.` or `terraform`). |
| `vars_folder` | **Yes** | — | Folder with `*.tfvars` relative to `working_dir` (e.g. `envs` or `terraform/envs`). |
| `max_parallel` | No | `'10'` | Max parallel plans (1–10). |
| `backend_config` | No | `''` | Optional path to backend config file (relative to `working_dir`). |
| `terraform_version` | No | `'1.9.0'` | Terraform version for `setup-terraform`. |
| `init_timeout` | No | `'300'` | Timeout in seconds for `terraform init`. |
| `plan_timeout` | No | `'600'` | Timeout in seconds for `terraform plan` (increase for 100+ workspaces or heavy refresh). |
| `github_token` | No | `github.token` | Token for creating/updating/closing the drift issue. |
| `repo` | No | `github.repository` | `owner/repo` for the drift issue. |
| `exclude` | No | `''` | **Expected drift:** patterns to exclude from drift count. Newline- or comma-separated, or JSON array. Each pattern matches if the resource address contains it. Use `workspace:substring` to scope to one workspace. Excluded changes appear in the report under "Excluded (expected) drift". |

### Expected drift (exclude)

To treat some changes as **expected** (e.g. known benign drift), set `exclude` so they are not counted as drift and do not fail the run:

- **Substring:** any resource whose address contains the string is excluded (e.g. `module.foo` or `aws_instance.bar`).
- **Scoped:** `workspace:substring` — only exclude when the workspace name matches and the address contains the substring (e.g. `staging:module.cron`).

Format: newline- or comma-separated list, or a JSON array string.

```yaml
- name: Terraform Drift Auditor
  uses: ./devtools-landingzone/actions/drift-auditor
  with:
    vars_folder: 'envs'
    exclude: |
      module.tags
      prod:module.legacy
```

### Example (in a workflow)

```yaml
- name: Configure AWS credentials (OIDC)
  if: vars.TF_EXEC_IAM_ROLE != ''
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ vars.TF_EXEC_IAM_ROLE }}
    aws-region: ${{ vars.TF_EXEC_ROLE_REGION || 'us-east-1' }}

- name: Terraform Drift Auditor
  uses: ./devtools-landingzone/actions/drift-auditor
  with:
    working_dir: '.'
    vars_folder: 'envs'
    max_parallel: '10'
    terraform_version: '1.9.0'
    github_token: ${{ secrets.GITHUB_TOKEN }}
    repo: ${{ github.repository }}
```

A full sample workflow (cron + manual) is in **`workflows/drift-check/drift-check.yml`** in this repo (sample/testing only; not published to `.github/workflows`).

---

## Running the script locally

Useful for testing or running outside GitHub Actions. You need Terraform installed and AWS (or backend) credentials configured.

```bash
# From repo root (working_dir = .)
python3 devtools-landingzone/actions/drift-auditor/drift_auditor.py \
  --working-dir . \
  --vars-folder envs \
  --max-parallel 10

# With backend config and GitHub issue (optional)
export GITHUB_TOKEN=ghp_...
python3 devtools-landingzone/actions/drift-auditor/drift_auditor.py \
  --working-dir terraform \
  --vars-folder terraform/envs \
  --backend-config backend.hcl \
  --github-token "$GITHUB_TOKEN" \
  --repo owner/repo
```

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--working-dir` | `.` | Terraform working directory. |
| `--vars-folder` | *(required)* | Folder containing `*.tfvars` (relative to `working_dir` or absolute). |
| `--max-parallel` | `10` | Max parallel plans (capped 1–10). |
| `--plugin-cache-dir` | env or `.tf-plugin-cache` | Override `TF_PLUGIN_CACHE_DIR`. |
| `--backend-config` | — | Path to backend config file. |
| `--init-timeout` | `300` | Timeout in seconds for `terraform init`. |
| `--plan-timeout` | `600` | Timeout in seconds for `terraform plan`. |
| `--github-token` | `GITHUB_TOKEN` | Token for GitHub API. |
| `--repo` | `GITHUB_REPOSITORY` | `owner/repo` for the drift issue. |
| `--exclude` | — | Expected drift: exclude changes whose address contains this (repeatable). Use `workspace:substring` to scope. |

```bash
# Exclude expected drift (repeatable or newline-separated in one value)
python3 devtools-landingzone/actions/drift-auditor/drift_auditor.py \
  --vars-folder envs \
  --exclude 'module.tags' \
  --exclude 'staging:module.legacy'
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean: no drift, no zombie state, no config/run errors. |
| `1` | Error: config or runtime failure (e.g. init/plan failed for one or more workspaces). |
| `2` | Drift (or zombie state): at least one workspace has changes or there are zombie workspaces. |

Use in a workflow: fail the job on non-zero so drift/errors are visible (e.g. status check or notifications).

---

## Outputs

- **Console** – Log lines prefixed with `[DRIFT-AUDIT]`; summary of workspaces and any errors.
- **File** – `drift-report.md` in the workspace root (or `GITHUB_WORKSPACE` in CI) with:
  - Summary table (clean / drift / error / zombie counts)
  - Zombie workspaces list (state in S3, no `.tfvars`)
  - Drift table (workspace, resource address, actions)
  - Error details per workspace
- **Artifact** – In the composite action, `drift-report.md` is uploaded as the `drift-report` artifact when present.
- **GitHub Issue** – When `github_token` and `repo` are set: one open issue **"Infrastructure Drift Report"** is created/updated with the report body, or closed when drift is resolved.

---

## Zombie state

A **zombie** is a workspace that exists in the S3 backend (from `terraform workspace list`) but has no corresponding `*.tfvars` in `vars_folder`. The auditor reports these so you can either add a tfvars file or remove the workspace/state.

- **Default workspace:** If `default` is in the zombie list, the report includes a security note: resources in the default workspace (with no `default.tfvars`) can be shadow infra; add `default.tfvars` to audit it or clean up the default state.
- **New workspaces:** If a developer adds a `.tfvars` file but hasn’t run the first apply yet, the workspace won’t exist in S3. The auditor runs plan and reports no drift; it does **not** flag that as a zombie. That’s intended: the workspace is declared in code and will get state on first apply.

---

## Configurable timeouts

Init and plan use timeouts so one stuck run doesn’t hang the job. Defaults: **300s** init, **600s** plan. For 100+ workspaces or heavy `-refresh=true` on large AWS envs, increase `--plan-timeout` (and optionally `--init-timeout`) via CLI or action inputs `init_timeout` / `plan_timeout` so you don’t have to edit the script.

---

## Provider cache and ARC (Kubernetes) runners

The action sets `TF_PLUGIN_CACHE_DIR` to `${{ github.workspace }}/.terraform.d/plugin-cache` so providers are shared across workers and can persist across runs when the workspace is on a persistent volume.

On **ARC / Kubernetes** runners, use a volume that allows **concurrent reads** (standard K8s volumes do). If you use an unusual storage driver, 10 processes reading the same provider binary can occasionally hit IO lock wait; prefer a fast, concurrent-friendly volume for the workspace (or reduce `max_parallel` if needed).

### Zero-touch ARC workflow example

```yaml
- name: Run Drift Auditor
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    TF_PLUGIN_CACHE_DIR: ${{ github.workspace }}/.terraform.d/plugin-cache
  run: |
    python3 drift_auditor.py \
      --vars-folder "./infra/vars" \
      --max-parallel 8 \
      --backend-config "./infra/backend.hcl"
```

Or call the composite action with the same options; it already sets the provider cache path.

---

## Backend config

If your S3 backend requires a config file (e.g. role, key prefix), pass it via the action input `backend_config` or the script flag `--backend-config`. The path is relative to `working_dir` (or absolute). It is passed to `terraform init -backend-config <path>` in each worker.
