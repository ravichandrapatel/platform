# Platform Component Manager – Test and Release Checklist

Use this to **test** the Platform Component Manager workflow and then **release each action and each workflow one at a time**.

---

## Tagging standard

| Branch   | Tags | Meaning |
|----------|------|--------|
| **main** | **component-v1** | Single stable pointer; always points to latest release (e.g. `owasp-dependency-check-v1`). |
| **main** | **component-1.0.0**, **component-1.0.1**, … | Version tags (SemVer); **at least last 10 kept**; older pruned only if beyond 10 and older than 14 days. |
| **develop** | **component-1.0.0-rc**, **component-1.0.1-rc**, … | **RC tags** only; multiple are fine (one per RC run). |

- Consumers use **component-v1** for “latest stable” (e.g. `uses: org/repo/devtools-landingzone/actions/owasp-dependency-check@owasp-dependency-check-v1`).
- No v2, v3, …; only **v1** is the stable pointer. **At least the last 10 version tags** are always kept; older are pruned only if beyond 10 and older than 14 days.

**Full spec:** [TAGGING-STRATEGY.md](TAGGING-STRATEGY.md) – lifecycle, derivation, rollback, consumer patterns.

---

**Prerequisites:**
- `develop` and `main` branches exist; RC runs on `develop`, promote on `main`.
- **Workflow must run from repo root:** GitHub only runs workflows under **`.github/workflows/` at the repository root**. If your repo root is `IDP` and the file lives under `devtools-landingzone/.github/workflows/platform-component-manager.yml`, copy it to **`IDP/.github/workflows/platform-component-manager.yml`** (and commit) so the Platform Component Manager appears in Actions. Then use the checklist below.
- For IDP repo: use `component_path` with `devtools-landingzone/` prefix (e.g. `devtools-landingzone/actions/owasp-dependency-check`).

---

## 1. Code review (done)

- [x] **Path allowlist** – Workflow accepts `actions/name`, `workflows/name`, and `devtools-landingzone/actions|workflows/name`.
- [x] **Type detection** – Workflow vs action detected for both plain and `devtools-landingzone/` paths.
- [x] **Tag prune regex** – Pruning allows tags with `devtools-landingzone/` prefix.
- [x] **Inputs** – `component_path`, `version` (SemVer), `mode` (rc | promote | rollback); all validated.
- [x] **Security** – Checkov (full repo + component workflow), ShellCheck, Bandit, no `write-all`, attestation.
- [x] **Execute** – RC tag on develop; promote: RC gate, workflow copy to `.github/workflows/`, stable tags, prune, changelog; rollback: restore workflows, move major pointer.

---

## 2. Components to release (one at a time)

### Actions (6)

| # | component_path | Suggested first version |
|---|----------------|--------------------------|
| 1 | `devtools-landingzone/actions/owasp-dependency-check` | 1.0.0 |
| 2 | `devtools-landingzone/actions/git-path-filter` | 1.0.0 |
| 3 | `devtools-landingzone/actions/drift-auditor` | 1.0.0 |
| 4 | `devtools-landingzone/actions/prbot` | 1.0.0 |
| 5 | `devtools-landingzone/actions/janitor-bot` | 1.0.0 |
| 6 | `devtools-landingzone/actions/issues-bot` | 1.0.0 |

### Workflows (6)

| # | component_path | Suggested first version |
|---|----------------|--------------------------|
| 7 | `devtools-landingzone/workflows/compliance` | 1.0.0 |
| 8 | `devtools-landingzone/workflows/dependency-check-nightly` | 1.0.0 |
| 9 | `devtools-landingzone/workflows/nodejs-app` | 1.0.0 |
| 10 | `devtools-landingzone/workflows/terraform` | 1.0.0 |
| 11 | `devtools-landingzone/workflows/terraform-refresh-daily` | 1.0.0 |
| 12 | `devtools-landingzone/workflows/drift-check` | 1.0.0 |

---

## 3. Test the workflow (single component)

1. **Trigger from `develop`** (Actions → Platform Component Manager → Run workflow):
   - **component_path:** `devtools-landingzone/actions/git-path-filter` (or any one from the table)
   - **version:** leave empty (auto-derived)
   - **mode:** `rc`
2. Confirm: **validate** → **security-spvs** → **security-gate** → **execute** all succeed.
3. Confirm RC tag exists (e.g. `git-path-filter-1.0.0-rc`).

---

## 4. Release each component (one at a time)

For **each** action and workflow:

### Step A – RC on develop

1. Branch: **develop** (and run from develop).
2. Actions → **Platform Component Manager** → Run workflow:
   - **component_path:** (e.g. `devtools-landingzone/actions/owasp-dependency-check`)
   - **version:** leave empty (auto-derived: latest+patch or 1.0.0)
   - **mode:** `rc`
3. Wait for green; verify RC tag exists (e.g. `devtools-landingzone/actions/owasp-dependency-check/1.0.0-rc`).

### Step B – Promote on main

1. Merge **develop** → **main** (or ensure the commit that has the RC tag is on main).
2. Actions → **Platform Component Manager** → Run workflow on **main**:
   - **component_path:** (same as above)
   - **version:** leave empty (auto-derived: latest RC)
   - **mode:** `promote`
3. Wait for green. For **workflows**, confirm `.github/workflows/` was updated on main.
4. Verify stable tag and major pointer (v1); pruning keeps 5 sub-tags.

### Step C – Next component

Repeat Step A and B for the next component (e.g. next row in the table). Release **one at a time** to avoid concurrency and to catch any component-specific issues.

---

## 5. Optional: local validation (no GitHub)

From repo root (IDP):

```bash
# Path check (use same allowlist as workflow)
PATH_NAME="devtools-landingzone/actions/owasp-dependency-check"
[[ -d "$PATH_NAME" ]] && echo "OK" || echo "Missing"

# Action metadata
grep -q '^name:' "$PATH_NAME/action.yml" && grep -q '^runs:' "$PATH_NAME/action.yml" && echo "action.yml OK"
```

With **act** (if configured): run the workflow locally; see `devtools-landingzone/act/readme.md`.

---

## 6. Rollback (if needed)

To point the major pointer (v1) back to an older version:

- **component_path:** same as released (e.g. `devtools-landingzone/actions/owasp-dependency-check`)
- **version:** leave empty (auto-derived: previous release) or set a specific version (e.g. `1.0.0`)
- **mode:** `rollback`

Run from **main**. This moves the major tag to the target version; for workflows it also restores `.github/workflows/` from that tag.
