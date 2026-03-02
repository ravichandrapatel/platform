# Standard naming convention (GitHub Actions / Terraform workflow)

Use these rules for workflow files under `.github/` and for the Terraform pipeline so names are consistent and predictable.

## Documentation (README)

| Item | Convention | Example |
|------|------------|---------|
| Readme in a folder | `readme.md` (lowercase) | `platform/actions/drift-auditor/readme.md`, `platform/addons/vault/readme.md` |
| Topic-specific readme at platform root or .github | `readme-<topic>.md` (full kebab-case) | `readme-platform-component-manager.md`, `.github/readme-terraform.md` |
| Other documentation (.md) | kebab-case (lowercase, hyphen-separated) | `naming.md`, `architecture-terraform.md`, `rules-writing-scripts-actions-workflows.md`, `compliance.md` |

All `.md` files under `platform/` use this so links and tooling stay consistent.

## Workflow

| Item | Convention | Example |
|------|------------|--------|
| Workflow name | Title case, noun | `Terraform` |
| Workflow file | kebab-case | `terraform.yml` |

## Jobs

| Item | Convention | Example |
|------|------------|--------|
| Job id | kebab-case, verb-noun or stage-noun | `detect-changes`, `terraform-checks`, `preprocessing`, `terraform-plan`, `plan-summary`, `opa` |
| Job comment | Stage number + short description | `# Stage 1: Detect changes ...` |

## Steps

| Item | Convention | Example |
|------|------------|--------|
| Step name | Title case, verb then object (optional qualifier in parentheses) | `Setup Terraform`, `Capture plan output (single)` |
| Step id | lowercase, short noun | `refs`, `changes`, `matrix` |

## Outputs

| Item | Convention | Example |
|------|------------|--------|
| Job outputs | snake_case | `changes_json`, `batch_matrix`, `plan_mode`, `batch_size` |
| Step outputs | snake_case (when set in run) | `source`, `base`, `matrix` |

## Environment variables

| Item | Convention | Example |
|------|------------|--------|
| Workflow / job env | SCREAMING_SNAKE_CASE, prefix for domain | `TF_WORKING_DIR`, `TF_VERSION`, `TF_EXEC_IAM_ROLE`, `TF_EXEC_ROLE_REGION`, `TF_OPA_POLICY_PATH`, `FULL_MATRIX`, `PLAN_MODE`, `BATCH_SIZE` |
| Prefix | `TF_` for Terraform workflow globals | — |
| Private modules (GitHub App) | Repo **variable** `TF_MODULES_APP_ID`, repo **variable** `TF_MODULES_APP_OWNER` (optional), repo **secret** `TF_MODULES_APP_PRIVATE_KEY` | Used by `actions/create-github-app-token` so `terraform init` can clone private Git module repos. |

## Workflow inputs (workflow_dispatch)

| Item | Convention | Example |
|------|------------|--------|
| Input key | snake_case | `working_directory`, `terraform_version`, `terraform_exec_iam_role`, `opa_policy_path` |

## Artifacts

| Item | Convention | Example |
|------|------------|--------|
| Artifact name | kebab-case; prefix for type | `plan-<workspace>`, `plan-batch-<n>`, `plan-summary` |
| Plan JSON (OPA) | `plan-<workspace>.json` | — |
| Plan binary (apply) | `plan-<workspace>.binary` | — |

## Files (generated in jobs)

| Item | Convention | Example |
|------|------------|--------|
| Plan human-readable | `plan.txt` | — |
| Plan summary markdown | `plan.md` | — |
| Artifact directory | kebab-case | `plan-artifacts` |

## Policy / config paths

| Item | Convention | Example |
|------|------------|--------|
| OPA policy bundle | path from repo root, no trailing slash | `platform/policies/terraform` |
| Git-path-filter group | lowercase | `tfvars` |

## Terraform resources (reference)

For `.tf` and Terraform code, use the project convention: **`{env}-{project}-{resource}-{suffix}`** (see `.cursor/rules/terraform-terragrunt.mdc`). Workspace names in this workflow are derived from `.tfvars` basename (e.g. `dev.tfvars` → workspace `dev`).
