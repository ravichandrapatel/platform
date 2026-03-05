# Terraform workflow — architecture and diagrams

This document describes the Terraform CI/CD workflow with diagrams that show triggers, stages, job dependencies, conditions, inputs, outputs, and artifacts. Reading the diagrams should convey the full design.

---

## 1. Trigger and pipeline overview

```mermaid
flowchart LR
  subgraph TRIGGERS["Triggers (path: **/*.tfvars)"]
    T1["push\nbranches: main"]
    T2["pull_request\nbranches: main"]
    T3["workflow_dispatch\n(manual)"]
  end

  subgraph PIPELINE["Pipeline stages"]
    S1["1. detect-changes"]
    S2["2. terraform-checks"]
    S3["3. preprocessing"]
    S4["4. terraform-plan\n(matrix, max 10)"]
    S5["5. plan-summary"]
    S6["6. opa"]
    S7["7. terraform-apply\n(main only)"]
  end

  T1 --> PIPELINE
  T2 --> PIPELINE
  T3 --> PIPELINE

  S1 --> S2 --> S3 --> S4 --> S5
  S4 --> S6
  S4 --> S7
  S6 --> S7
```

**Takeaways:** Three triggers; seven stages; apply (7) runs only after OPA (6) and only on main.

---

## 2. Full workflow (triggers, conditions, jobs, artifacts)

```mermaid
flowchart TB
  subgraph TRIGGERS["Triggers"]
    direction TB
    PUSH["push: branches [main]\npaths: **/*.tfvars"]
    PR["pull_request: branches [main]\npaths: **/*.tfvars"]
    MANUAL["workflow_dispatch\n(inputs: working_directory, terraform_version,\nterraform_exec_iam_role, terraform_exec_role_region, opa_policy_path)"]
  end

  subgraph ENV["Workflow env (from inputs or defaults)"]
    E["TF_WORKING_DIR, TF_VERSION,\nTF_EXEC_IAM_ROLE, TF_EXEC_ROLE_REGION,\nTF_OPA_POLICY_PATH"]
  end

  TRIGGERS --> ENV
  ENV --> DETECT

  subgraph STAGE1["Stage 1: detect-changes"]
    DETECT["Job: detect-changes"]
    D1["1.1 Checkout (fetch-depth: 0)"]
    D2["1.2 Set refs (source/base)\n dispatch→ref_name/default_branch\n PR→head_ref/base_ref\n push→sha/before"]
    D3["1.3 git-path-filter\ntfvars: **/*.tfvars"]
    DETECT --> D1 --> D2 --> D3
    OUT1["Outputs: changes, changes_json\n(tfvars.has_changes, tfvars.files[])"]
    D3 --> OUT1
  end

  OUT1 --> COND2{"tfvars.has_changes\nor workflow_dispatch?"}
  COND2 -->|yes| STAGE2
  COND2 -->|no| SKIP["Skip stages 2–7"]

  subgraph STAGE2["Stage 2: terraform-checks"]
    CHECKS["Job: terraform-checks"]
    C1["2.1 Checkout"]
    C2["2.2 Setup Terraform"]
    C3["2.3 init -backend=false"]
    C4["2.4 validate"]
    C5["2.5 fmt -check"]
    CHECKS --> C1 --> C2 --> C3 --> C4 --> C5
  end

  STAGE2 --> STAGE3

  subgraph STAGE3["Stage 3: preprocessing"]
    PRE["Job: preprocessing"]
    M1["3.1 Build matrix\nworkspace = basename(.tfvars)\ntfvars_file = path\nslice [0:10]"]
    PRE --> M1
    OUT3["Output: matrix\n[{workspace, tfvars_file}, ...]"]
    M1 --> OUT3
  end

  OUT3 --> COND4{"matrix != []?"}
  COND4 -->|yes| STAGE4
  COND4 -->|no| SKIP

  subgraph STAGE4["Stage 4: terraform-plan (matrix)"]
    PLAN["Job: terraform-plan\nstrategy: fail-fast false\nmatrix: from preprocessing"]
    P1["4.1 Checkout"]
    P2["4.2 AWS OIDC (if role set)"]
    P3["4.3 Setup Terraform"]
    P4["4.4 terraform init"]
    P5["4.5 Resolve var-file path\nworkspace select/new\nterraform plan -out=tfplan"]
    P6["4.6 terraform show -json → .json\ncp tfplan → .binary\n→ plan-artifacts/"]
    P7["4.7 terraform show -no-color → plan.txt"]
    P8["4.8 awk/sed plan.txt → plan.md\n→ GITHUB_STEP_SUMMARY"]
    P9["4.9 Upload artifact\nplan-<workspace>"]
    PLAN --> P1 --> P2 --> P3 --> P4 --> P5 --> P6 --> P7 --> P8 --> P9
    ART4["Artifacts: plan-dev, plan-staging, ...\n(each: .json + .binary)"]
    P9 --> ART4
  end

  ART4 --> STAGE5
  ART4 --> STAGE6
  ART4 --> STAGE7

  subgraph STAGE5["Stage 5: plan-summary"]
    SUM["Job: plan-summary\nif: plan success or failure"]
    S1["5.1 Download plan-* (merge)"]
    S2["5.2 Write plan-summary.md\ntable + failure note if any"]
    S3["5.3 GITHUB_STEP_SUMMARY\nUpload plan-summary"]
    SUM --> S1 --> S2 --> S3
    ART5["Artifact: plan-summary\n(plan-summary.md)"]
    S3 --> ART5
  end

  subgraph STAGE6["Stage 6: OPA"]
    OPA["Job: opa\nif: plan success"]
    O1["6.1 Checkout"]
    O2["6.2 Download plan-*"]
    O3["6.3 Install OPA"]
    O4["6.4 opa eval -i plan-*.json -d policy\ndata.terraform.plan.allow\nfail if != true"]
    OPA --> O1 --> O2 --> O3 --> O4
  end

  O4 --> COND7{"ref == refs/heads/main\nand OPA success?"}
  COND7 -->|yes| STAGE7
  COND7 -->|no| NOAPPLY["Apply not run\n(PR or non-main)"]

  subgraph STAGE7["Stage 7: terraform-apply (matrix)"]
    APPLY["Job: terraform-apply\nmatrix: same as plan\nfail-fast: false"]
    A1["7.1 Checkout"]
    A2["7.2 AWS OIDC (if role set)"]
    A3["7.3 Setup Terraform"]
    A4["7.4 Download plan-<workspace>"]
    A5["7.5 terraform init"]
    A6["7.6 workspace select"]
    A7["7.7 terraform apply -auto-approve\nplan-<workspace>.binary"]
    APPLY --> A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A7
  end
```

**Takeaways:** One diagram shows triggers, env, all seven stages, step numbers, outputs/artifacts, and conditions (tfvars changed, matrix non-empty, ref=main + OPA success).

---

## 3. Job dependency graph

```mermaid
flowchart LR
  D["detect-changes"]
  C["terraform-checks"]
  P["preprocessing"]
  PL["terraform-plan\n(matrix)"]
  PS["plan-summary"]
  O["opa"]
  A["terraform-apply\n(matrix)"]

  D --> C
  D --> P
  C --> P
  P --> PL
  PL --> PS
  PL --> O
  PL --> A
  O --> A
```

**Takeaways:** Linear chain 1→2→3→4; then 4 feeds 5, 6, and 7; 6 also feeds 7.

---

## 4. Data flow (outputs and artifacts)

```mermaid
flowchart TB
  subgraph OUT["Job outputs"]
    O1["detect-changes\nchanges_json"]
    O3["preprocessing\nmatrix"]
  end

  subgraph ART["Artifacts"]
    A4["plan-<workspace>\n.json + .binary"]
    A5["plan-summary\n.md"]
  end

  subgraph CONSUMERS["Consumers"]
    O1 --> C1["terraform-checks, preprocessing\n(if tfvars.has_changes)"]
    O3 --> C2["terraform-plan matrix"]
    O3 --> C3["terraform-apply matrix"]
    A4 --> C4["plan-summary\n(merge plan-*)"]
    A4 --> C5["opa\n(plan-*.json)"]
    A4 --> C6["terraform-apply\n(plan-<workspace> per job)"]
  end

  O1 --> PRE["preprocessing\n(reads tfvars.files)"]
  PRE --> O3
  PLAN["terraform-plan"] --> A4
  A4 --> PS["plan-summary"]
  PS --> A5
```

**Takeaways:** `changes_json` drives preprocessing; `matrix` drives plan and apply; plan artifacts feed summary, OPA, and apply.

---

## 5. Trigger → outcome matrix

```mermaid
flowchart TB
  subgraph FEATURE["Feature branch"]
    F1["Push"]
    F2["No auto-trigger"]
    F3["Run workflow (manual)"]
    F1 -.-> F2
    F2 --> F3
    F3 --> F4["Plan runs (stages 1–6)\nApply skipped (not main)"]
  end

  subgraph PR["Pull request to main"]
    PR1["Open/update PR"]
    PR2["Auto-trigger (path filter)"]
    PR3["Stages 1–6 run"]
    PR4["Apply skipped"]
    PR5["Merge only if Terraform check passes"]
    PR1 --> PR2 --> PR3 --> PR4 --> PR5
  end

  subgraph MAIN["Merge to main"]
    M1["Merge PR"]
    M2["Push event to main"]
    M3["Auto-trigger"]
    M4["Stages 1–7 run\nApply runs (matrix)"]
    M1 --> M2 --> M3 --> M4
  end
```

**Takeaways:** Feature branch = manual run, plan only. PR = auto plan + OPA, no apply; merge = full pipeline including apply.

---

## 6. Stage and step index (reference)

| Stage | Job | Steps |
|-------|-----|-------|
| 1 | detect-changes | 1.1 Checkout, 1.2 Set refs, 1.3 git-path-filter |
| 2 | terraform-checks | 2.1 Checkout, 2.2 Setup Terraform, 2.3 init -backend=false, 2.4 validate, 2.5 fmt -check |
| 3 | preprocessing | 3.1 Build matrix (max 10) |
| 4 | terraform-plan | 4.1 Checkout, 4.2 AWS OIDC, 4.3 Setup Terraform, 4.4 init, 4.5 plan, 4.6 .json/.binary, 4.7 plan.txt, 4.8 summary, 4.9 upload artifact |
| 5 | plan-summary | 5.1 Download plan-*, 5.2 Write summary, 5.3 Upload plan-summary |
| 6 | opa | 6.1 Checkout, 6.2 Download plan-*, 6.3 Install OPA, 6.4 opa eval |
| 7 | terraform-apply | 7.1 Checkout, 7.2 AWS OIDC, 7.3 Setup Terraform, 7.4 Download plan, 7.5 init, 7.6 workspace select, 7.7 apply |

---

## 7. Component and action summary

| Component | Type | Purpose |
|------------|------|---------|
| **terraform.yml** | Workflow | Defines triggers, env, jobs, steps. |
| **devtools-landingzone/actions/git-path-filter** | Composite action | Detects changed files by pattern (tfvars). |
| **devtools-landingzone/policies/terraform** | Rego bundle | OPA policies; default `plan.rego` (allow). |
| **actions/checkout@v4** | Action | Checkout repo. |
| **actions/create-github-app-token@v2** | Action | Create installation token for private Git module repos (when `TF_MODULES_APP_ID` set). |
| **hashicorp/setup-terraform@v3** | Action | Install Terraform. |
| **aws-actions/configure-aws-credentials@v4** | Action | AWS OIDC assume-role. |
| **actions/upload-artifact@v4** | Action | Upload plan-*, plan-summary. |
| **actions/download-artifact@v4** | Action | Download plan-* (merge or by name). |

---

For the detailed README (inputs, env, artifacts, branch protection), see [readme-terraform.md](readme-terraform.md).
