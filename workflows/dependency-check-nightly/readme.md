# OWASP Dependency-Check (nightly)

Builds and pushes the **owasp-dependency-check** container image to GHCR.

## Purpose

- Build the image from `devtools-landingzone/images/owasp-dependency-check/` (UBI9, OWASP Dependency-Check CLI).
- Push to the configured registry (e.g. `ghcr.io/org/owasp-dependency-check`) for use by the action and by compliance scans.

## When it runs

- Typically **scheduled** (e.g. nightly) or **manual** via workflow_dispatch. If you use it in this repo, publish the workflow to `.github/workflows/` so GitHub can run it.

## Relation to platform

- **Compliance** workflow pulls and scans this image; it does not build it. This workflow is the build source for the image. Whether you keep it here as reference or publish to `.github/workflows/` depends on repo policy.
