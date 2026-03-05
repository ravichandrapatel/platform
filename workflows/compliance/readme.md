# Compliance

Canonical source for the **Compliance** workflow.

## Purpose

- **Trivy** config and filesystem scan for each platform image (Buildah/Podman); build and push only when Critical=0.
- Updates the compliance table in the root **readme** and **compliance.md** after each run.
- **When it runs:** First Sunday of month (cron) or manual via Actions → Compliance. Inputs: `image_to_build` (ALL or single image name), `registry`, `pull_registry`.

## Where it lives

- **Source:** `devtools-landingzone/workflows/compliance/compliance.yml`
- **Published:** `.github/workflows/compliance.yml` (so GitHub runs it on schedule and `workflow_dispatch`).

Pipeline security aligns with **OWASP SPVS**; see [owasp-spvs.md](../../owasp-spvs.md) and [devsecops-spvs-standard.md](../../devsecops-spvs-standard.md).
