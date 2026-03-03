# Security

Security policy and standards for the platform repository.

## Reporting a vulnerability

If you believe you have found a security vulnerability, please report it privately (e.g. to the maintainers or via your organization’s secure channel). Do not open a public issue for security-sensitive findings.

## Standards and compliance

We align with **OWASP Secure Pipeline Verification Standard (SPVS) v1.0** for pipeline and release security.

- **Technical standard (checklists and implementation):** [devsecops-spvs-standard.md](devsecops-spvs-standard.md)  
  Use this for code review, CI gates, and onboarding. It covers:
  - GitHub Actions & workflow hardening (identity, OIDC, environments, SHA pinning, attestation)
  - Python scripting (subprocess safety, path handling, input validation, dependencies)
  - Shell scripting (safe header, quoting, no direct context in `run`, ShellCheck)
  - Automated verification (rulesets, secret scanning, Dependabot, protected environments, Checkov/ShellCheck)

- **SPVS overview and how we use it:** [owasp-spvs.md](owasp-spvs.md)

- **Release workflow and full-repo SPVS validation:** [platform-component-manager.md](platform-component-manager.md) (Stage 2: Security SPVS).

## Quick checklist

Before merging or releasing, ensure:

- Workflows use least-privilege `permissions:` and no broad write-all.
- Python uses list-based `subprocess` (no `shell=True`), no `eval`/`exec`/`os.system()`, and validated inputs (e.g. Pydantic).
- Shell scripts start with `set -euo pipefail`, quote variables `"$VAR"`, and do not use `${{ }}` inside `run:` (use `env:` instead).
- CI runs ShellCheck on `.sh` and Checkov (`github_actions`) on workflow YAML; dependencies are scanned (e.g. Dependabot).

For the full checklist and examples, see [devsecops-spvs-standard.md](devsecops-spvs-standard.md).
