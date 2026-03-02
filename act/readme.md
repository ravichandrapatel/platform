# Local testing with act

Use [act](https://github.com/nektos/act) to run GitHub Actions workflows locally via Docker. This gives a fast feedback loop for workflow and action changes without pushing to GitHub.

## Prerequisites

- **Docker** (or Podman with Docker compat): act runs jobs in containers.
- **act**: Install e.g. via [releases](https://github.com/nektos/act/releases), Homebrew (`brew install act`), or your package manager.

## Custom runner image (no public image)

We use a **local-only** runner image so act does not pull any public third-party image (e.g. catthehacker/ubuntu). You must build it once:

```bash
# From repo root
./platform/act/runner/build.sh
```

This builds **`act-runner:latest`** from `platform/act/runner/Containerfile` (Ubuntu 22.04 + git, python3, pip, buildah, gh). `run.sh` uses it by default with `-P ubuntu-latest=act-runner:latest --pull=false`. To use the default public image instead, pass **`--no-custom-image`**.

## Layout

- Workflows live in **`platform/.github/*.yml`** (not under `.github/workflows/`). act is pointed at that directory with `-W platform/.github`.
- **Run act from the repository root** so that `./platform/actions/<name>` and paths like `platform/images/` resolve correctly.
- **`platform/act/runner/`** holds the custom image Containerfile and `build.sh`.

## Quick start

From the **repo root** (`IDP/`):

```bash
# Build the custom runner image (required once)
./platform/act/runner/build.sh

# List workflows and jobs (dry run)
./platform/act/run.sh -n

# Run a specific workflow (workflow_dispatch)
./platform/act/run.sh dependency-check-nightly

# Run with secrets from a file
./platform/act/run.sh dependency-check-nightly --secret-file platform/act/.env
```

Copy `platform/act/.env.example` to `platform/act/.env` (or your own secret file) and fill in values. Do not commit `.env`.

## run.sh usage

```text
./platform/act/run.sh [OPTIONS] [WORKFLOW]

Options:
  -n, --dry-run       List jobs only, do not run
  -j, --job NAME      Run only this job (default: all jobs in the workflow)
  -e, --event EV      Event (default: workflow_dispatch)
  -s, --secret K=V    Pass secret (repeatable); overrides env file
  --secret-file F     Use F as .env-style secret file (default: none)
  --no-custom-image   Use default (public) runner image instead of local act-runner

Workflow: base name of the workflow file without .yml (e.g. dependency-check-nightly, drift-check).
          If omitted, act lists all workflows.
```

Examples:

```bash
./platform/act/run.sh -n
./platform/act/run.sh -n dependency-check-nightly
./platform/act/run.sh dependency-check-nightly --secret-file platform/act/.env
./platform/act/run.sh drift-check -j drift-audit --secret-file platform/act/.env
```

## Workflow matrix

| Workflow                     | act-friendly | Requirements | Notes |
|-----------------------------|--------------|--------------|--------|
| **dependency-check-nightly** | Yes          | `GITHUB_TOKEN`; optional `NVD_API_KEY` | Buildah/Podman in runner; push to GHCR if token has `packages: write`. |
| **drift-check**             | Partial      | AWS (OIDC or keys), `GITHUB_TOKEN` | Needs Terraform state (e.g. S3); use mock/skip AWS for action-only test. |
| **compliance**              | Partial      | `GITHUB_TOKEN` | Matrix + Trivy; can run with small matrix or single image. |
| **platform-component-manager** | Yes       | `GITHUB_TOKEN` (with repo + tags) | Mostly shell + `gh`; good for testing job steps. |
| **terraform**               | No*          | AWS, GitHub App, OPA, many jobs | Heavy; use CI or manual trigger for real runs. |
| **terraform-refresh-daily** | No*          | AWS, GitHub App | Same as above. |

\* Can be run with act if you provide all secrets and accept long runtimes; not recommended for quick local iteration.

## Secrets and env

- **GITHUB_TOKEN**: Required for checkout and (for some workflows) API/registry. Use a PAT with `repo` and, if pushing images, `write:packages`.
- **NVD_API_KEY**: Optional for dependency-check-nightly (NVD rate limits without it).
- **AWS_* / OIDC**: For drift-check and terraform workflows; omit for local action-only tests.

See `platform/act/.env.example` for a template. Pass secrets with `--secret-file` or `-s KEY=value`; never commit real secrets.

## Tips

- Use **`-n`** first to see which jobs would run and catch workflow syntax issues.
- To test only a **single action** (e.g. `git-path-filter` or `drift-auditor`), run the smallest workflow that uses it, or use `-j` to run one job.
- The **custom image** is used by default; use `--no-custom-image` only if you need the default public runner image.
- Workflows that call **reusable workflows** (e.g. from another repo) may not resolve locally; prefer workflows that use only `./platform/actions/` and public actions.
