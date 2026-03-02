# OWASP Dependency Check

Run **OWASP Dependency-Check** in CI using a pre-built container image. The action uses **Podman** only (no Docker) and is intended for runners that have Podman installed—for example, ARC (Actions Runner Controller) runner pods. **Proxy-related options are not exposed** in this action.

The container image is built and pushed by this repo’s **OWASP Dependency-Check (nightly)** workflow. [Dependency-Check CLI arguments](https://dependency-check.github.io/DependencyCheck/dependency-check-cli/arguments.html) are exposed as action inputs (except proxy).

---

## Requirements

- **Podman** must be available on the runner. The action will fail with a clear error if only Docker is present.
- Use a runner that provides Podman (e.g. a self-hosted ARC runner with the owasp-dependency-check or gha-runner-scale-set-runner image).

---

## How to use the action

### From this repo

```yaml
- uses: actions/checkout@v4

- name: OWASP Dependency-Check
  uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: HTML
```

### From another repo

Pin to a tag for stability. You must pass the **image** input because the default image is from the current repo.

```yaml
- uses: actions/checkout@v4

- name: OWASP Dependency-Check
  uses: YOUR_ORG/IDP/platform/actions/owasp-dependency-check@v1.0.0
  with:
    project: my-app
    path: .
    format: HTML
    image: ghcr.io/YOUR_ORG/IDP/owasp-dependency-check:latest
```

---

## Inputs (action.yml)

### Required

| Input    | Description |
|----------|-------------|
| `project` | Project name (used in reports). |
| `path`    | Path to scan, relative to the workspace (e.g. `.`, `src`, `backend`). |
| `format`  | Report format: `HTML`, `XML`, `CSV`, `JSON`, `JUNIT`, `SARIF`, `JENKINS`, `GITLAB`, or `ALL`. |

### Common optional

| Input          | Default   | Description |
|----------------|-----------|-------------|
| `out`          | `reports` | Output directory for reports (relative to workspace). |
| `image`        | (GHCR from this repo) | Full image reference (e.g. `ghcr.io/org/repo/owasp-dependency-check:latest`). Required when using the action from another repo. |
| `failOnCVSS`   | —         | Fail the step if any vulnerability has CVSS ≥ this (0–10). Example: `7`. |
| `suppression`  | —         | Path(s) to suppression XML files, comma-separated; or HTTP(S) URLs. Paths are relative to workspace. |
| `exclude`      | —         | Path patterns to exclude from scan, comma-separated. |
| `noupdate`     | `true`    | When `true`, skip NVD/suppressions update (faster; use cached data). Set to `false` to allow update. |
| `nvdApiKey`    | —         | NVD API key (recommended for higher rate limits). Use a repo secret. |
| `nvdApiDelay`  | —         | Delay in ms between NVD API requests (e.g. `3500` with key, `6000` without). |

### Boolean options (default: false unless noted)

Many CLI flags are exposed as boolean inputs. Set to `true` to pass the flag. Examples:

- **Updates / data:** `noupdate` (default `true`), `updateonly`, `purge`
- **Analyzers:** `disableNodeJS`, `disableMSBuild`, `disableGolangMod`, `disableComposer`, `disableRetireJS`, etc.
- **Node:** `nodeAuditSkipDevDependencies`, `nodePackageSkipDevDependencies`
- **Reporting:** `prettyPrint` (for JSON/XML)
- **Failures:** use `failOnCVSS` or `junitFailOnCVSS` for threshold-based failure

The full list is in `action.yml`; see also the [Dependency-Check CLI arguments](https://dependency-check.github.io/DependencyCheck/dependency-check-cli/arguments.html).

---

## Report formats

- **HTML** – Human-readable report; good for artifacts and manual review.
- **SARIF** – For GitHub Code Scanning / Security tab; upload with `github/codeql-action/upload-sarif` or a SARIF upload step.
- **JUNIT** – For test-style integration (e.g. JUnit report aggregation).
- **JSON / XML** – For parsing or custom tooling.
- **ALL** – Generate all formats in the output directory.

Reports are written under the workspace path given by `out` (default `reports`). Use `actions/upload-artifact` to persist them.

---

## Examples

### Basic scan (HTML report)

```yaml
- uses: actions/checkout@v4
- name: Dependency-Check
  uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-service
    path: .
    format: HTML
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: dependency-check-report
    path: reports/
```

### Fail on high/critical (CVSS ≥ 7)

```yaml
- uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: HTML
    failOnCVSS: '7'
```

### With suppression file

Keep a suppression XML in the repo (e.g. `dependency-check-suppressions.xml`) and reference it:

```yaml
- uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: HTML
    suppression: dependency-check-suppressions.xml
```

Multiple files (or URLs): comma-separated, e.g. `suppression: suppressions.xml,https://example.com/suppressions.xml`.

### NVD API key (recommended for CI)

Reduces rate limiting and speeds up updates when `noupdate: false`:

```yaml
- uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: HTML
    nvdApiKey: ${{ secrets.NVD_API_KEY }}
    nvdApiDelay: '3500'
    noupdate: false
```

Create an [NVD API key](https://nvd.nist.gov/developers/request-an-api-key) and store it in a repo or org secret.

### SARIF for GitHub Security tab

```yaml
- uses: actions/checkout@v4
- name: Dependency-Check
  id: dc
  uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: SARIF
    out: sarif
- uses: github/codeql-action/upload-sarif@v3
  if: success() && always()
  with:
    sarif_file: sarif/dependency-check-report.sarif
```

(Adjust the `sarif_file` path if your image writes a different filename.)

### Scan a subdirectory

```yaml
- uses: ./platform/actions/owasp-dependency-check
  with:
    project: backend-api
    path: backend
    format: HTML
```

### Exclude paths

```yaml
- uses: ./platform/actions/owasp-dependency-check
  with:
    project: my-app
    path: .
    format: HTML
    exclude: '**/node_modules/**,**/vendor/**,**/dist/**'
```

---

## Outputs and artifacts

The action does not define outputs; it writes reports to the directory specified by `out`. To keep reports:

- Use `actions/upload-artifact` to upload the `out` directory (e.g. `reports/` or `sarif/`).
- For SARIF, use `github/codeql-action/upload-sarif` to feed the Security tab.

---

## Image and versioning

- **Default image:** `ghcr.io/<github.repository>/owasp-dependency-check:latest` when the action runs in this repo.
- **From other repos:** Set the `image` input (e.g. `ghcr.io/YOUR_ORG/IDP/owasp-dependency-check:latest`) and pin the action ref (e.g. `@v1.0.0`).
- The image is built by the **Dependency-Check UBI9 (nightly)** workflow in this repo and pushed to GHCR. Use the same image reference in `image` that your org publishes.

---

## References

- [OWASP Dependency-Check](https://owasp.org/www-project-dependency-check/)
- [Dependency-Check CLI arguments](https://dependency-check.github.io/DependencyCheck/dependency-check-cli/arguments.html)
- [NVD API key](https://nvd.nist.gov/developers/request-an-api-key)
