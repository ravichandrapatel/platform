# 🚀 Platform Component Change Request

## 🏗️ Change Overview
- **Component Path:** `actions/<name>` or `workflows/<name>`
- **Proposed Version:** (e.g., 1.2.0)
- **Change Type:** [🆕 New | 🛠️ Fix | ✨ Feature | 🚨 Security]

## 🛡️ SPVS Security Checklist (Self-Attestation)
### 1. GitHub Actions & Workflows
- [ ] **Least Privilege:** New permissions required: `________________` (or N/A).
- [ ] **Hardened Headers:** All `.sh` files start with `set -euo pipefail`.
- [ ] **No Shell Injection:** No `${{ }}` used in `run:`. All context mapped to `env`.
- [ ] **Integrity:** 3rd-party actions pinned to **SemVer (vX.Y.Z)** or **Commit SHA**.

### 2. Code Hardening
- [ ] **Python:** No `shell=True` in subprocess; `black` formatting applied.
- [ ] **Python:** Payload validation via Pydantic or type hints.
- [ ] **Validation:** Local `shellcheck` / `bandit` results attached as screenshots.

## 🧪 Testing & Validation
- [ ] **RC Tag Tested:** Mode `rc` run successfully. Run URL: `________________`
- [ ] **Documentation:** `/docs` updated with security grade and inputs/outputs.
- [ ] **Integration:** Component verified in a live test workflow.

---
*By submitting this PR, I certify this change aligns with the [STANDARD.md](STANDARD.md).*