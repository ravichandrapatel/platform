# Node.js App CI Workflow

Pipeline for Node.js applications: **setup → lint → test → build → security (npm audit) → OWASP Dependency-Check → SonarCloud → Buildah image**.

## Features

| Stage        | Description |
|-------------|-------------|
| **Setup**   | Checkout, setup Node.js (with npm cache), install dependencies |
| **Lint**    | `npm run lint` or `npx eslint .` if no script |
| **Test**    | `npm test` (skipped if no script) |
| **Build**   | `npm run build`; uploads `dist/` as artifact |
| **Security**| `npm audit --audit-level=high` (non-blocking) |
| **OWASP**   | OWASP Dependency-Check (platform action or container image) |
| **Sonar**   | SonarCloud scan (requires `SONAR_TOKEN`) |
| **Image**   | Buildah build and push to GHCR (main/master only; requires `Containerfile` in context) |

## Usage

### From this repo (platform)

When this workflow is under `.github/workflows/` (e.g. after platform component manager publish):

- **Triggers:** push/PR to `main`/`master`, or **Run workflow** with optional `node_version`, `working_directory`.
- **Secrets:** `SONAR_TOKEN` (SonarCloud), optional `NVD_API_KEY` (OWASP), `GITHUB_TOKEN` (packages).

### Reusable from another repo

```yaml
# .github/workflows/ci.yml in your Node.js app repo
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  nodejs-ci:
    uses: YOUR_ORG/platform/.github/workflows/nodejs-app.yml@main
    with:
      node_version: '20'
      working_directory: '.'
      project_name: my-app
      image_name: my-app
      containerfile_path: Containerfile
      context_path: .
      run_owasp: true
      run_sonar: true
      run_image_build: true
    secrets: inherit
```

### Requirements in your app

- **package.json** with optional scripts: `lint`, `test`, `build`.
- **Containerfile** (or `Dockerfile`) at `context_path` for the image job.
- **SonarCloud:** add repo in SonarCloud, set `SONAR_TOKEN` in the calling repo.

## YAML anchors in this workflow

The workflow uses **anchors** and **aliases** to avoid repeating the same steps and job defaults. Only three symbols are involved (there is no `%` in standard YAML for anchors).

| Symbol | Name | Meaning |
|--------|------|--------|
| **`&name`** | Anchor | Define a label on a node so it can be reused elsewhere. The node is defined once (e.g. a step or a `defaults` block). |
| **`*name`** | Alias | Reference the anchored node. The full node (all keys and values) is reused as-is. |
| **`<<: *name`** | Merge key | Merge the anchored node *into* the current mapping. Keys in the current mapping override keys from the merged node. |

**Examples from `nodejs-app.yml`:**

- **Anchor + alias (reuse whole node):**
  ```yaml
  # Defined once in setup-lint-test:
  defaults: &defaults-run
    run:
      working-directory: ${{ env.WORKING_DIR }}

  # Reused in build, security, sonar:
  defaults: *defaults-run
  ```
  `*defaults-run` is a copy of the whole `defaults-run` node.

- **Anchor on a step, alias in other jobs:**
  ```yaml
  # In setup-lint-test:
  - &checkout
    name: Checkout
    uses: actions/checkout@v4

  # In build, security, owasp, image:
  - *checkout
  ```
  Each `*checkout` is the same step (same name, same `uses`).

- **Merge to reuse but override one key:**
  ```yaml
  # In owasp (defines the anchor):
  - &install-buildah
    name: Install Buildah (if no Podman/Buildah)
    run: | ...

  # In image job: same run script, different step name
  - <<: *install-buildah
    name: Install Buildah
  ```
  `<<: *install-buildah` merges the anchored step into this step; `name: Install Buildah` overrides the original `name`.

Anchors are defined the first time a block appears; later jobs use `*anchor` or `<<: *anchor` to reuse it. Expressions like `${{ env.WORKING_DIR }}` are preserved in the anchored content and evaluated at run time.

## Release

Use the **Platform Component Manager** to publish this workflow to `.github/workflows/` and tag it (e.g. `workflows/nodejs-app/1.0.0`).
