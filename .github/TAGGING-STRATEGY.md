# Platform Component Manager – Tagging Strategy

Per-component, numeric SemVer lifecycle with RC testing, stable releases, rollbacks, and cleanup.

---

## Tag anatomy

Tags use the **component name** (last segment of `component_path`), not the full path, so consumers can reference a short ref after `@`:

```
Format:        [component-name]-[version[-rc]]  or  [component-name]-v1
Examples (component_path = devtools-landingzone/actions/security-scan → name = security-scan):
  security-scan-2.0.0          (version tag – main)
  security-scan-2.0.0-rc        (RC tag – develop only)
  security-scan-v1              (stable pointer – always latest on main)
```

**Consumer reference:** `uses: ORG/REPO/devtools-landingzone/actions/security-scan@security-scan-v1`

---

## Lifecycle flow

### Step 1: RC mode (develop branch)

- **Trigger:** `workflow_dispatch`, `mode=rc`, `component_path=actions/security-scan` (or `devtools-landingzone/actions/...`).
- **Version:** Optional. If omitted, **derived**: latest version tag + **patch bump** (e.g. 1.9.5 → 1.9.6), or 1.0.0 if no tags. If provided, must be SemVer X.Y.Z.
- **Creates:** `security-scan-2.0.0-rc` (or derived e.g. 1.9.6-rc).
- **Branch:** develop.

### Step 2: Promote mode (main branch)

- **Trigger:** `workflow_dispatch`, `mode=promote`, same `component_path`.
- **Gates:**
  - RC tag exists (e.g. `security-scan-2.0.0-rc`).
  - RC commit SHA matches main HEAD.
  - New version ≥ existing latest (SemVer).
- **Actions:**
  - For **workflows:** copy component YAML to `.github/workflows/`, commit and push.
  - Create **version tag** (e.g. `security-scan-2.0.0`).
  - Move **v1** to point to that release: `security-scan-v1` → same commit.
  - Delete RC tag (`security-scan-2.0.0-rc`).
  - **Prune:** keep **at least the last 10 version tags** (component-X.Y.Z). Delete older version tags only if they are (a) beyond the 10 most recent and (b) older than 14 days; **never delete the tag v1 points to**. Also delete **RC tags (component-X.Y.Z-rc) older than 14 days**. v1 itself is never deleted.
- **Result:** v1 always points to latest release on main.

### Step 3: Rollback mode (main branch)

- **Trigger:** `workflow_dispatch`, `mode=rollback`.
- **Version:** Optional. If omitted, **derived**: previous (second-newest) version tag. If provided, that version is used.
- **Actions:**
  - Restore `.github/workflows/` from target version (if workflow component).
  - Move **v1** to point to target version tag (e.g. 1.9.5).
  - **Delete the version tag we rolled back from** (e.g. 2.0.0), so the reverted release is removed.
- **Validation:** v1 SHA matches target version tag SHA.

---

## Tag states (example)

Component path `devtools-landingzone/actions/security-scan` → tag prefix `security-scan`:

```
INITIAL STATE (main):
  security-scan-v1     → 1.9.5
  security-scan-1.9.5
  security-scan-1.9.4
  ... (version tags kept until older than 14 days)

AFTER RC (develop):
  security-scan-2.0.0-rc   ← new

AFTER PROMOTE (main):
  security-scan-v1     → 2.0.0   ← moved
  security-scan-2.0.0   ← new
  (version tags older than 14 days are pruned)

AFTER ROLLBACK (main):
  security-scan-v1     → 1.9.5   ← moved back
```

---

## Concurrency and isolation

- **Concurrency group:** `pcm-${{ component_path }}` (e.g. `pcm-actions/security-scan`).
- Each component is independent; no cross-contamination.
- Multiple components can be RC’d or promoted in parallel by different users.
- **v1** is per-component; no global coordination.

---

## Consumer reference patterns

Use the **path** for the action/workflow and the **short tag** after `@` (component name + `-v1` or `-X.Y.Z`):

```yaml
# Latest stable (auto-updates when you re-run or on next fetch)
- uses: org/repo/devtools-landingzone/actions/security-scan@security-scan-v1

# Pin to a specific version (e.g. rollback)
- uses: org/repo/devtools-landingzone/actions/security-scan@security-scan-1.9.5

# Reusable workflow (component name = workflow folder name, e.g. compliance)
jobs:
  scan:
    uses: org/repo/.github/workflows/spvs-scan.yml@compliance-v1
```

---

## Security and gates

- SPVS: full-repo Checkov (GitHub Actions) before any release.
- Component: ShellCheck, Bandit (CLI), least-privilege check, attestation.
- RC → main: RC tag exists, SHA matches main HEAD.
- SemVer: no version regression on promote.
- Provenance attestation (SLSA-style).
- Environment protection (staging/production).
- Prune: keep at least last 10 version tags; delete only tags beyond those 10 and older than 14 days (never the tag v1 points to). RC tags older than 14 days deleted. v1 never pruned.

---

## Properties

| Property | Implementation |
|----------|-----------------|
| Latest always current | v1 force-moved on every promote |
| Rollback ready | At least last 10 version tags always kept; older pruned only if &gt;10 and &gt;14 days |
| RC safety | develop-only; RC tag deleted on promote |
| Team isolation | Per-component lifecycle (concurrency group) |
| Numeric only | X.Y.Z (SemVer) |
| SPVS aligned | Full security gates + provenance |

---

## Implementation note (version derivation)

- **RC, version empty:** **Latest on main** = the version of the tag that **v1** points to (canonical current release). Next RC = **minor bump** (e.g. 2.0.0 → 2.1.0-rc). If v1 doesn’t exist or doesn’t point to a version tag, fall back to highest version tag in repo, or `1.0.0`. So the **main branch** is the starting point for the next RC version; multiple RCs from develop then promote in order without version collisions.
- **Promote, version empty:** version from **latest RC tag** (that RC is promoted).
- **Rollback, version empty:** **previous** (second-newest) version tag.

**Version tracking:** For RC, **main** is the starting point: the version **v1** points to is "latest on main"; we **minor bump** from that (e.g. 2.0.0 → 2.1.0-rc). So if current latest is 2.0.0 and you run RC from develop, you get 2.1.0-rc. User B’s next RC would be 2.2.0-rc after 2.1.0 is promoted—no collisions. The source of truth for “last release” is **version tags** on main (component-X.Y.Z). RC tags are ephemeral (pruned after 14 days); they are not used to derive the next version. So you always know the last release and can bump correctly.
