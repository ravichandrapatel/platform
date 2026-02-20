# Platform – reusable actions and container images

Single folder for **custom reusable actions** and **container images** used by this repo and by application teams. All builds use **Buildah or Podman only** (no Docker). No CodeQL; compliance is Trivy on images.

---

## Layout

| Path | Purpose |
|------|--------|
| **actions/** | Composite reusable actions (use from workflows with `uses: org/repo/platform/actions/NAME@ref`) |
| **images/** | Containerfiles and build context for images (Buildah/Podman) |
| **workflows/** | Workflow definitions (run from `.github/workflows/`; paths reference `platform/`) |
| **CHANGELOG.md** | Changelog for actions and images |

---

## Reusable actions

### dependency-check-ubi9

**Path:** `platform/actions/dependency-check-ubi9/`

Runs OWASP Dependency-Check using a pre-built UBI9 image. Requires **Podman** on the runner (e.g. ARC runner pod).

**Use from this repo:**
```yaml
- uses: ./platform/actions/dependency-check-ubi9
  with:
    project: my-app
    path: .
    format: HTML
```

**Use from another repo (application teams):** Pin to a release tag for stability.
```yaml
- uses: YOUR_ORG/IDP/platform/actions/dependency-check-ubi9@v1.0.0   # or @main for latest
  with:
    project: my-app
    path: .
    format: HTML
    # When using from another repo, pass the platform image (built and pushed by this repo):
    image: ghcr.io/YOUR_ORG/IDP/dependency-check-ubi9:latest
```

See [Releasing](#releasing) for how we publish versions so app teams can use `@v1.x.x`.

---

## Container images

<!-- IMAGES_TABLE_START -->
| Image | Path | Base | Purpose |
|-------|------|------|---------|
| **dependency-check-ubi9** | `platform/images/dependency-check-ubi9/` | UBI9 | OWASP Dependency-Check CLI (nightly build; compliance pulls and scans only). |
| **gh-actions-runner-podman** | `platform/images/gh-actions-runner-podman/` | UBI9 | ARC self-hosted runner with rootless Podman/Buildah. |
| **gha-runner-scale-set-controller-ubi9** | `platform/images/gha-runner-scale-set-controller-ubi9/` | UBI9 minimal | ARC controller (binaries copied from upstream; no distroless). |
<!-- IMAGES_TABLE_END -->

### Adding a new image

1. Create **`platform/images/<id>/`** with at least a **Containerfile** (and any scripts it needs).
2. Add optional **`platform/images/<id>/image-info.yaml`** with `name`, `base`, `purpose` for the README table.
3. Add an entry to **`platform/images/images.yaml`**:
   - `id`: same as folder name.
   - `pull_only: true` if the image is built elsewhere (e.g. nightly) and compliance should only pull and scan.
   - `pull_only: false` and optional `build_args` (e.g. `TARGETPLATFORM=linux/amd64`) if compliance should build it.

The compliance workflow and README table will pick it up automatically.

### Build tags

- **dependency-check-ubi9:** Built by nightly; compliance pulls `ghcr.io/<repo>/dependency-check-ubi9:latest` and scans.
- **gh-actions-runner-podman:** Built in compliance or locally; tag e.g. `ghcr.io/org/gh-actions-runner:latest`.
- **gha-runner-scale-set-controller-ubi9:** Built in compliance or locally; tag e.g. `ghcr.io/org/gha-runner-scale-set-controller:ubi9-0.13.1`.

### Compliance status

<!-- COMPLIANCE_TABLE_START -->
<!-- Badge and link inserted by update_readme.py (run with --repo owner/repo for badge) -->
Full table: [compliance.md](compliance.md)
<!-- COMPLIANCE_TABLE_END -->

Workflow **Compliance** (`.github/workflows/compliance.yml`) runs on the first Sunday of each month (and on demand): Trivy config+fs per image, optional build+push when Critical=0, then updates this table. For each image:

- **Trivy config + fs** runs in each `images/<name>/` folder; results are written to `trivy-results.json`.
- **Build and push** (Docker) runs only when **Critical** vulnerabilities are 0.
- The table above is updated by `scripts/update_readme.py` after all scans complete.


---

## Workflows

Workflows that build or scan platform images live in **`.github/workflows/`** (GitHub only runs from there). They reference `platform/images/` and `platform/actions/` by path. Copies of the workflow files are kept under **`platform/workflows/`** for reference.

| Workflow | Purpose |
|----------|--------|
| Dependency-Check UBI9 (nightly) | Build and push dependency-check-ubi9 image to GHCR |
| Compliance | First Sunday of month + manual: Trivy config+fs per image (matrix, max 4); build+push only if Critical=0; updates compliance table in README |

---

## Releasing (workflows and actions only; no third-party actions)

Release and tag promotion use only `run:` (git + `gh` CLI).

### Develop – release candidate

- **On push to `develop`** (e.g. when a PR is merged to develop): the workflow updates a **single** tag **`1.0.0-rc`** to the latest develop commit (force-update). Reuse the same RC tag for fixes; only one RC tag is kept.

### Main – stable

- **On push to `main`** (promotion after testing): the workflow promotes to stable:
  1. If tag **`1.0.0`** already exists, the **previous** commit is archived as **`1.0.0-<short-sha>`**.
  2. Tag **`1.0.0`** is force-updated to the new main commit (latest code = `1.0.0`).
  3. A **GitHub Release** is created for `1.0.0` with notes from `platform/CHANGELOG.md`.
  4. **Tag pruning:** only the **last 10 tags** on main are kept (`1.0.0` + up to 9 archived `1.0.0-<sha>`); older archived tags are deleted.

### Usage for application teams

- **Stable (production):** `uses: YOUR_ORG/IDP/platform/actions/dependency-check-ubi9@1.0.0`
- **Release candidate (testing):** `uses: YOUR_ORG/IDP/platform/actions/dependency-check-ubi9@1.0.0-rc`

When using from another repo, pass the **image** input (e.g. `ghcr.io/YOUR_ORG/IDP/dependency-check-ubi9:latest`).
