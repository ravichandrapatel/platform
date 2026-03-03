# OWASP SPVS alignment

We align pipeline security with **OWASP Secure Pipeline Verification Standard (SPVS)** where applicable.

## What is SPVS?

**SPVS** is an OWASP framework (v1.0, October 2025) for assessing and standardizing security maturity of software delivery pipelines across the full lifecycle:

| Stage      | Focus |
|-----------|--------|
| **Plan**  | Scope, objectives, security requirements, risk baselines |
| **Develop** | Secure code, vulnerability detection, code review |
| **Integrate** | Security tests, artifact integrity, automated validation |
| **Release** | Artifact integrity, change control, secure rollout |
| **Operate** | Monitoring, incident response, access control, resilience |

- **References:** [owasp.org/www-project-spvs](https://owasp.org/www-project-spvs) · [GitHub: OWASP/www-project-spvs](https://github.com/OWASP/www-project-spvs)
- Multi-tiered maturity; aligns with CIS, OWASP ASVS, cloud Well-Architected.

## How we use it

- **Compliance workflow** (Trivy, Buildah, GHCR): **Integrate** / **Release** (scan, build, push) and **Operate** (visibility).
- **OWASP Dependency-Check** (action/image): **Develop** and **Integrate** (dependency/SCA scanning).

No separate “SPVS release” of Dependency-Check; we use current versions and map controls to SPVS stages as above.

**Detailed technical standard (checklists, Python/Shell/GitHub Actions):** [devsecops-spvs-standard.md](devsecops-spvs-standard.md).
