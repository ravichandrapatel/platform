# 🚀 Platform Component Change Request

## 📋 Governance & Tracking
- **Jira Story/Task:** [e.g., PLAT-1234]
- **SR/Ticket Number:** [Mandatory for Hotfix/Bugfix: e.g., SR-98765]
- **Component Path:** `actions/<name>` or `workflows/<name>`

## 🏗️ Change Overview
- **Change Type:** [🆕 New | 🛠️ Fix | ✨ Feature | 🚨 Security | 🔥 Hotfix]

## 🛡️ SPVS Security Checklist (Self-Attestation)
### 1. GitHub Actions & Workflows
- [ ] **Least Privilege:** New permissions required: `________________` (or N/A).
- [ ] **Hardened Headers:** All `.sh` files start with `set -euo pipefail`.
- [ ] **No Shell Injection:** No `${{ }}` used in `run:`. All context mapped to `env`.
- [ ] **Integrity:** 3rd-party actions pinned to **vX.Y.Z** or **Commit SHA**.

### 2. Code Hardening
- [ ] **Python:** No `shell=True` in subprocess; `black` formatting applied.
- [ ] **Python:** Payload validation via Pydantic or type hints.
- [ ] **Validation:** Local `shellcheck` / `bandit` results attached as screenshots.

## 🧪 Testing & Validation
- [ ] **RC Tag Tested:** Mode `rc` run successfully. Run URL: `________________`
- [ ] **Documentation:** Component readme (or platform handbook in `readme.md`) updated with security grade and inputs/outputs.
- [ ] **Integration:** Component verified in a live test workflow.

---
*By submitting this PR, I certify this change aligns with the [devsecops-spvs-standard.md](../devsecops-spvs-standard.md).*
