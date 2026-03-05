# Terraform CI/CD Workflow

GitHub Actions workflow for Terraform: detect changed `.tfvars` files, run checks and plan (with optional OPA policy evaluation), and apply on merge to `main` only. No direct push to `main`; all changes enter via pull request.

---

## Table of contents

- [Overview](#overview)
- [Triggers](#triggers)
- [Pipeline stages](#pipeline-stages)
- [Data source refresh (daily cache)](#data-source-refresh-daily-cache)
- [Inputs and environment](#inputs-and-environment)
- [Artifacts](#artifacts)
- [Branch protection](#branch-protection)
- [Naming](#naming)
- [Architecture diagram](#architecture-diagram)

---

## Overview

| Item | Description |
|------|-------------|
| **Workflow file** | `terraform.yml` |
| **Stages** | 7: detect-changes → checks → preprocessing → plan → plan-summary → OPA → apply |
| **Scope** | Changed `**/*.tfvars` only (path filter). Max 10 workspaces per run. |
| **Apply** | Runs only on `refs/heads/main` (e.g. after PR merge). |

**Flow in short**

1. **Feature branch:** Push does not trigger. Use **Run workflow** (manual) to run plan, fix, then open PR.
2. **Pull request to main:** Workflow runs from detect-changes through OPA (no apply). Require this workflow as a status check so merge is allowed only when all jobs pass.
3. **Merge to main:** Push to `main` runs the full pipeline including apply (one apply job per planned workspace).

---

## Triggers

| Trigger | When | Path filter | What runs |
|---------|------|-------------|-----------|
| **push** | Pushes to branch `main` | `**/*.tfvars` | Full pipeline (stages 1–7). Apply runs only on `main`. |
| **pull_request** | PRs targeting `main` | `**/*.tfvars` | Stages 1–6 (no apply). |
| **workflow_dispatch** | Manual “Run workflow” | — | Stages 1–6 always; stage 7 (apply) only if run is on `main` and OPA passed. |

- Feature-branch pushes do **not** trigger the workflow (only `push` to `main` is defined).
- Main is updated only via PR merge; the push that triggers apply is the merge push.

---

## Pipeline stages

### Stage 1: Detect changes

- **Job:** `detect-changes`
- **Purpose:** Find which `*.tfvars` files changed between source ref and base ref.
- **Implementation:** In-repo action `devtools-landingzone/actions/git-path-filter` with pattern `tfvars: ['**/*.tfvars']`.
- **Outputs:** `changes`, `changes_json` (contains `tfvars.has_changes`, `tfvars.files[]`).
- **Steps:**
  - 1.1 Checkout (full history).
  - 1.2 Set source/base refs (dispatch vs PR vs push).
  - 1.3 Run git-path-filter.

Downstream stages (2–7) run only when `tfvars.has_changes` is true or the run is `workflow_dispatch`.

---

### Stage 2: Terraform checks

- **Job:** `terraform-checks`
- **Needs:** Stage 1.
- **Purpose:** Validate Terraform config and formatting without backend or cloud credentials.
- **Steps:**
  - 2.1 Checkout
  - 2.2 Create GitHub App token for private modules (if `TF_MODULES_APP_ID` set)
  - 2.3 Configure Git for private Terraform modules (so `terraform init` can clone private Git module repos)
  - 2.4 Setup Terraform (`TF_VERSION`)
  - 2.5 `terraform init -backend=false`
  - 2.6 `terraform validate`
  - 2.7 `terraform fmt -check -recursive -diff`

---

### Stage 3: Preprocessing

- **Job:** `preprocessing`
- **Needs:** Stage 1, Stage 2.
- **Purpose:** Build the plan matrix from changed `.tfvars`: workspace name = basename without `.tfvars`, one entry per file; cap at **10 workspaces** per run.
- **Output:** `matrix` = `[{workspace, tfvars_file}, ...]` (max 10).
- **Steps:**
  - 3.1 Build matrix with jq; output `matrix` for plan and apply.

---

### Stage 4: Terraform plan

- **Job:** `terraform-plan`
- **Needs:** Stage 1, Stage 3.
- **Strategy:** Matrix over `preprocessing.outputs.matrix`; `fail-fast: false`.
- **Purpose:** For each workspace: init, select/create workspace, plan with `-var-file`, then produce `.json` (OPA) and `.binary` (apply), capture human-readable plan, display summary, upload artifact.
- **Steps (per matrix job):**
  - 4.1 Checkout
  - 4.2 Create GitHub App token for private modules (if `TF_MODULES_APP_ID` set)
  - 4.3 Configure Git for private Terraform modules
  - 4.4 Configure AWS credentials (OIDC) if `TF_EXEC_IAM_ROLE` set
  - 4.5 Setup Terraform
  - 4.6 `terraform init`
  - 4.7 Resolve `var-file` path for `TF_WORKING_DIR`; workspace select/new; `terraform plan -out=tfplan -var-file=...`
  - 4.8 Generate `plan-<workspace>.json` and `plan-<workspace>.binary`; copy to `plan-artifacts/`
  - 4.9 `terraform show -no-color tfplan > plan.txt`
  - 4.10 Build markdown from plan.txt; append to `GITHUB_STEP_SUMMARY`
  - 4.11 Upload artifact `plan-<workspace>` (contains `.json` + `.binary`)

If `TF_WORKING_DIR` is set, the workflow resolves the var-file path relative to the working directory so plan finds the correct `.tfvars` file.

---

### Stage 5: Plan summary

- **Job:** `plan-summary`
- **Needs:** Stage 4.
- **Runs when:** Stage 4 succeeded or failed (so partial successes are summarized).
- **Purpose:** Combine all plan artifacts into one markdown table (workspace | .json | .binary), append to job summary, upload `plan-summary` artifact.
- **Steps:**
  - 5.1 Download all `plan-*` artifacts (merge).
  - 5.2 Write `plan-summary.md` (table; if any plan job failed, note count of successful plans).
  - 5.3 Append summary to `GITHUB_STEP_SUMMARY`; upload artifact `plan-summary`.

---

### Stage 6: OPA

- **Job:** `opa`
- **Needs:** Stage 4.
- **Runs when:** All terraform-plan jobs succeeded.
- **Purpose:** Evaluate each `plan-*.json` against Rego policies; query `data.terraform.plan.allow`; fail if any plan is denied.
- **Steps:**
  - 6.1 Checkout (for policy path)
  - 6.2 Download all `plan-*` artifacts
  - 6.3 Install OPA CLI
  - 6.4 For each `plan-*.json`, run `opa eval` with policy bundle at `TF_OPA_POLICY_PATH`; fail if `allow != true`.

Policy path default: `devtools-landingzone/policies/terraform` (see `devtools-landingzone/policies/terraform/plan.rego`).

---

### Stage 7: Apply

- **Job:** `terraform-apply`
- **Needs:** Stage 3, Stage 4, Stage 6.
- **Runs when:** `github.ref == 'refs/heads/main'` and Stage 6 succeeded.
- **Strategy:** Matrix over same `preprocessing.outputs.matrix`; `fail-fast: false`.
- **Purpose:** For each workspace: download plan artifact, init, workspace select, `terraform apply -auto-approve` with the plan `.binary`.
- **Steps (per matrix job):**
  - 7.1 Checkout
  - 7.2 Create GitHub App token for private modules (if `TF_MODULES_APP_ID` set)
  - 7.3 Configure Git for private Terraform modules
  - 7.4 Configure AWS credentials (OIDC) if set
  - 7.5 Setup Terraform
  - 7.6 Download artifact `plan-<matrix.workspace>`
  - 7.7 `terraform init`
  - 7.8 `terraform workspace select <workspace>`
  - 7.9 `terraform apply -auto-approve` with plan binary path

Apply runs only on the default branch (main); no direct push to main, only via PR merge.

---

## Data source refresh (daily cache)

Terraform does **not** support caching a data source for a fixed time. You can get “refresh once per day” by splitting who refreshes and who uses state:

1. **Daily job** runs **with** refresh and updates state (e.g. `terraform apply -refresh-only`). That re-queries all data sources and writes the result into state.
2. **Other runs** (e.g. PR/push) run **with** `-refresh=false` so they use the state from the last run and do **not** re-query data sources (they use the “cached” values from the daily refresh).

**Optional sample workflow:** `workflows/terraform-refresh-daily/terraform-refresh-daily.yml` runs on a schedule (e.g. once at 06:00 UTC), runs `terraform apply -refresh-only -auto-approve` per workspace so remote state is updated with fresh data source values. Copy/publish it into `.github/workflows/` only if you want to run it in GitHub.

**Using the cache in the main workflow:** The workflow uses **`-refresh=false`** on plan when the repository variable `TF_SKIP_REFRESH` is not set to `false`. So by default, PR/push plans use state (no data source API calls). Run the daily refresh workflow (or set `TF_SKIP_REFRESH=false` for a run) to update state. Trade-off: data source changes (e.g. new team in GitHub) are visible only after the next refresh.

**GitHub API rate limits:** When using the GitHub provider (e.g. `github-teams` or `github-branch-protection` modules), each plan that refreshes data sources can trigger many API calls (e.g. one per workspace for `github_organization_teams`). To avoid hitting limits: (1) keep the default `TF_SKIP_REFRESH` so plan uses state; (2) run the daily refresh workflow so state is updated once per day; (3) in configs with multiple `github-teams` modules, pass `organization_teams` from a single data source at root (see module README).

---

## Inputs and environment

**Workflow dispatch inputs**

| Input | Default | Description |
|-------|---------|-------------|
| `working_directory` | `.` | Terraform root (e.g. `terraform/`, `environments/dev`). |
| `terraform_version` | `1.9.0` | Terraform version. |
| `terraform_exec_iam_role` | — | IAM role ARN for OIDC (plan/apply). |
| `terraform_exec_role_region` | `us-east-1` | AWS region for that role. |
| `opa_policy_path` | `devtools-landingzone/policies/terraform` | Path to Rego policy bundle. |

**Private Terraform modules (GitHub)**

If your Terraform config uses **modules from private Git repos** (e.g. `github.com/org/terraform-modules//...`), configure a GitHub App so the workflow can clone them:

| Item | Where | Description |
|------|--------|-------------|
| **App ID** | Repository variable `TF_MODULES_APP_ID` | GitHub App ID (numeric). When set, the workflow uses `actions/create-github-app-token@v2` to create an installation token and configures Git so `terraform init` can pull private modules. |
| **Private key** | Repository secret `TF_MODULES_APP_PRIVATE_KEY` | The App’s private key (PEM, including `-----BEGIN/END RSA PRIVATE KEY-----`). Required when `TF_MODULES_APP_ID` is set. |
| **Owner** | Repository variable `TF_MODULES_APP_OWNER` (optional) | Org or user the App is installed on. Defaults to `github.repository_owner` if unset. |

The token step runs in **terraform-checks**, **terraform-plan**, and **terraform-apply**. If you do not use private Git modules, leave `TF_MODULES_APP_ID` unset and the steps are skipped.

---

**Environment (set from inputs on dispatch; defaults on push/PR)**

| Variable | Purpose |
|----------|---------|
| `TF_WORKING_DIR` | Terraform working directory. |
| `TF_VERSION` | Terraform version. |
| `TF_EXEC_IAM_ROLE` | Role for AWS OIDC. |
| `TF_EXEC_ROLE_REGION` | AWS region for OIDC. |
| `TF_OPA_POLICY_PATH` | OPA policy directory. |

On push/PR, inputs are not available; the workflow uses the defaults above (e.g. `TF_WORKING_DIR` = `.`).

---

## Artifacts

| Artifact name | Produced by | Contents |
|---------------|-------------|----------|
| `plan-<workspace>` | Stage 4 (each matrix job) | `plan-<workspace>.json`, `plan-<workspace>.binary` |
| `plan-summary` | Stage 5 | `plan-summary.md` |

- **plan-*.json:** Consumed by Stage 6 (OPA).
- **plan-*.binary:** Consumed by Stage 7 (apply).
- **plan-summary:** For humans and logs.

---

## Branch protection

To ensure the feature branch is clean before merge:

1. **Settings → Branches → Branch protection rule** for `main`.
2. Enable **Require status checks to pass before merging**.
3. Add the status check **Terraform** (this workflow).
4. Save.

Then PRs to `main` must have the Terraform workflow green before merge; after merge, the push to `main` runs the full pipeline including apply.

---

## Naming

Conventions for this workflow are in [.github/naming.md](naming.md): job ids (kebab-case), env (`TF_*`), artifacts (`plan-*`), step numbers (Stage.Step).

---

## Architecture diagram

See [architecture-terraform.md](architecture-terraform.md) for the full architecture and UML-style Mermaid diagrams (triggers, stages, dependencies, artifacts, conditions).
