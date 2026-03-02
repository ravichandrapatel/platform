## Platform Component Manager (RC → Promote → Rollback)

The **Platform Component Manager** workflow is the release automation “landing zone” for the platform monorepo.  
It owns the full lifecycle for **actions** and **reusable workflows**:

- **RCs on `develop`** (pre‑release candidates)
- **Promotions on `main`** (stable release)
- **Rollbacks** to any previous stable version
- **SemVer safety**, **tag pruning**, **environments**, and **auto‑changelog**

The workflow file is `platform/.github/workflows/platform-component-manager.yml`.

---

### Pipeline flow (Mermaid)

```mermaid
flowchart TD
  A[User runs 'Platform Component Manager'\nworkflow_dispatch] --> B[validate job\n(branch: current ref)]

  subgraph VALIDATE[Stage 1 – Validation & Gatekeeping]
    B1[Path Check\n- component_path folder must exist] --> B2[Type Detection\n- if starts with workflows/ → type=workflow\n- else → type=action]
    B2 --> B3[RC Gate (promote only)\n- ensure tag path/VER-rc exists on develop]
    B3 --> B4[SemVer Gate (promote only)\n- list path/[0-9]* tags\n- ensure VER >= latest\n- reject regressions]
    B4 --> B5[Action Metadata Check (actions/*)\n- ensure action.yml/.yaml exists\n- basic shape: name:, runs:]
  end

  B -->|needs: validate| C[execute job\n(branch: develop for rc, main otherwise)]

  subgraph EXECUTE[Stage 2 – Execution]
    direction TB
    C1[Checkout target branch\n- mode=rc → develop\n- promote/rollback → main\n- fetch-depth: 0\n- token: COMMIT_TOKEN or GITHUB_TOKEN] --> C2[Set Git identity]

    C2 --> D1[mode=rc\nCreate / update RC tag]
    C2 --> D2[mode=promote\nPromote RC to stable]
    C2 --> D3[mode=rollback\nMove stable pointer]

    D1 --> D1a[git tag -f path/VER-rc\non develop] --> D1b[git push origin path/VER-rc --force]

    subgraph PROMOTE[mode=promote on main]
      D2a[Self-healing RC check\n- RC tag path/VER-rc must exist\n- RC commit == main HEAD] --> D2b[Workflow sync (if type=workflow)\n- copy workflows/<name> → .github/workflows/\n- commit & push]
      D2b --> D2c[Tagging\n- determine PREV_TAG (previous path/[0-9]*)\n- create FULL_TAG path/VER\n- move STABLE path/vMAJOR\n- push tags]
      D2c --> D2d[Prune tags\n- list path/[0-9]* sorted desc\n- keep latest 5\n- delete older tags locally + remote]
      D2d --> D2e[Changelog\n- if PREV_TAG exists\n- git log PREV_TAG..HEAD -- path\n- append Markdown to summary]
      D2e --> D2done[Release complete]
    end

    subgraph ROLLBACK[mode=rollback on main]
      D3a[Find FULL_TAG path/VER\n- ensure it exists] --> D3b[Move stable tag\n- git tag -f path/vMAJOR FULL_TAG\n- git push origin path/vMAJOR --force]
    end
  end

  C -->|always()| E[audit job\n(GitHub summary)]

  subgraph AUDIT[Stage 3 – Audit & Summary]
    E1[Write $GITHUB_STEP_SUMMARY\n- component_path\n- mode\n- execute result\n- optional changelog section] --> EDone[Visible in Actions run UI]
  end

  classDef validate fill:#1f2933,stroke:#111827,color:#f9fafb
  classDef execute fill:#111827,stroke:#111827,color:#f9fafb
  classDef audit fill:#111827,stroke:#111827,color:#f9fafb
  class VALIDATE validate
  class EXECUTE execute
  class AUDIT audit
```

---

## What this manages in the platform

- **Actions:**  
  `actions/<name>/` (e.g. `actions/prbot`, `actions/git-path-filter`)  
  - `action.yml` / `action.yaml` is validated for basic structure.
  - Releases are just tags on the **main** branch; the action code stays in the monorepo.

- **Reusable workflows:**  
  `workflows/<name>/` or `platform/workflows/<name>/`  
  - Source of truth lives under `workflows/` or `platform/workflows/`.  
  - On **promote**, the workflow copies that folder’s `.yml` files into `.github/workflows/` and commits them; GitHub only runs workflows from `.github/workflows/`.  

Together, this gives you a single release pipeline for:

- **Platform actions** (under `actions/`)
- **Platform workflows** (under `workflows/` / `platform/workflows/`)

---

## Jobs and environments

### validate job

- Runs on **current ref** (branch you dispatch from).
- Responsibilities:
  - **Path check:** `component_path` must be an existing folder.
  - **Type detection:**  
    - If `component_path` starts with `workflows/` → `type = workflow`.  
    - Otherwise → `type = action`.
  - **RC gate for promote:**  
    - For `mode = promote`, require tag `path/VER-rc` to exist on `develop`.  
    - This enforces the “RC before promotion” discipline.
  - **SemVer gate for promote:**  
    - Enumerate all tags matching `path/[0-9]*`.  
    - Extract just the numeric versions, `sort -V`, and find the **latest existing** version.  
    - If the requested `version` would be **lower** than the latest, the workflow fails with a **version regression** error.
  - **Action metadata validation (actions only):**
    - Ensure `action.yml` or `action.yaml` exists in the component folder.
    - Check that it has at least `name:` and `runs:` at top level.

### execute job

- Runs on:
  - `develop` when `mode = rc`.
  - `main` when `mode = promote` or `rollback`.
- Uses GitHub **environments**:
  - `rc` → `staging` environment, URL → `develop` branch.  
  - `promote` / `rollback` → `production` environment, URL → `main` branch.
- Permissions: `contents: write`.
- Token:
  - `COMMIT_TOKEN` (if configured) is preferred; otherwise falls back to `GITHUB_TOKEN`.

What it does, per mode:

- **mode = rc (develop branch)**
  - Create or update `path/VER-rc` on `develop`.
  - Push with `--force`.
  - This is the “candidate” that must pass tests before promotion.

- **mode = promote (main branch)**
  - **Self-healing RC check:**
    - Resolve `path/VER-rc`.  
    - Ensure its commit **matches `main` HEAD**; if not, fail the promotion.  
    - This guarantees you only promote code that was really tested as that RC.
  - **Workflow sync (type = workflow):**
    - Copy `workflows/<name>/*.yml` (or `platform/workflows/<name>`) into `.github/workflows/`.
    - Commit and push to `main`. This new commit becomes the tag target.
  - **Tagging:**
    - Determine `PREV_TAG` (latest `path/[0-9]*` before creating this one).  
    - Create full tag `path/VER`.  
    - Move stable tag `path/vMAJOR` to the same commit, pushed with `--force`.
  - **Pruning:**
    - List all tags `path/[0-9]*` sorted by version descending.  
    - Keep the **newest 5**; delete any older tags locally and on `origin`.  
    - This implements a rolling window of 5 historical versions per component.
  - **Auto‑changelog:**
    - If `PREV_TAG` exists and differs from the new `path/VER`, run:  
      `git log --oneline --pretty=format:"* %s (%h)" PREV_TAG..HEAD -- path`  
    - Append the result as a Markdown section to `$GITHUB_STEP_SUMMARY` for quick release notes.

- **mode = rollback (main branch)**
  - Verify the requested `FULL_TAG = path/VER` exists.  
  - Move stable tag `path/vMAJOR` to point at that full tag’s commit.  
  - Push stable tag with `--force`.  
  - No new commits or full-version tags are created.

### audit job

- Always runs (`if: always()`).
- Appends a short summary to `$GITHUB_STEP_SUMMARY`:
  - `component_path`, `mode`, `needs.execute.result`.  
  - (For promotes) the auto‑changelog section from `execute`.

---

## Input contract

| Input | Required | Description |
|-------|----------|-------------|
| `component_path` | Yes | Platform component path: `actions/<name>` or `workflows/<name>` / `platform/workflows/<name>`. Must be a folder. |
| `version` | Yes | Semantic version (e.g. `1.2.0`). For `rc`, it is the RC version; for `promote`, the released version; for `rollback`, the version to point the stable tag at. |
| `mode` | Yes | `rc`, `promote`, or `rollback`. |

---

## Tag model (after refactor)

For a component `actions/my-action` and `version = 1.2.0`:

- **RC tag (develop):**  
  - `actions/my-action/1.2.0-rc`
- **Full (stable) tag (main):**  
  - `actions/my-action/1.2.0`
- **Major alias (stable pointer, main):**  
  - `actions/my-action/v1`

The workflow enforces:

- No promotion without a matching `*-rc` tag.
- No promotion that regresses relative to the latest existing full tag.
- At most **5 full-version tags** per component prefix (older ones are pruned).

---

## How this fits into the platform

At the platform level, this workflow provides:

- A **single, opinionated release flow** for:
  - Platform GitHub **actions** (in `actions/`).
  - Platform GitHub **workflows** (in `workflows/` / `platform/workflows/` → `.github/workflows/`).
- **Clear lifecycle states:**
  - `develop` + RC tags → staging.
  - `main` + full tags → production.
- **Guardrails and self‑healing:**
  - SemVer monotonicity.
  - RC–main commit parity check.
  - Basic action metadata validation.
  - Tag pruning and auto‑changelog for observability.

Consumers across the platform can then **standardize on tag patterns** like `actions/my-action/1.2.0` or `actions/my-action/v1` and rely on this workflow to keep those refs correct, safe, and tidy over time.

