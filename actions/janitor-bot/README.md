# Janitor Bot Action

Scan or cleanup **stale branches**, **pull requests**, **artifacts**, and **packages** for **one repo**, **multiple repos**, **entire org**, or **repos with a topic (tag)**. Configuration is **100% environment variables**—no JSON config file. You can **enable only what you need** (e.g. only artifacts, or only PRs) and use **name/pattern filters** for each. Ideal for use with `workflow_dispatch` so you can change scope and thresholds from the "Run workflow" UI.

## Features

- **Scope**: Run against a single repo, a list of repos, all repos in an org, or all org repos that have a given GitHub **topic** (tag).
- **Four cleanup types**: **Branches** (scan only; protected branches never touched), **PRs** (close stale open PRs), **Artifacts** (delete old workflow artifacts), **Packages** (delete old package versions, org-level). Enable any combination via `cleanup_branches`, `cleanup_prs`, `cleanup_artifacts`, `cleanup_packages`.
- **Pattern per type**: Each type can be restricted by a **glob pattern**—e.g. only branches matching `feature/*`, only artifacts named `plan-*`, only PRs from `release-*`, only packages named `my-app-*`.
- **Config via env**: All settings come from environment variables, which you map from workflow inputs in YAML.
- **Markdown report**: Writes `janitor_report.md` with thresholds and tables for branches, PRs, artifacts, and packages.
- **API throttling**: Rate-limit awareness and retry with backoff; optional delay between repos (`BATCH_DELAY_SECONDS`).

## Scope (what to scan)

| Scope   | Env / input      | Description |
|---------|------------------|-------------|
| `org`   | `SCOPE=org`      | All repositories in the organization (default). Requires `ORG_NAME`. |
| `repo`  | `SCOPE=repo` + `REPO` | Single repository. `REPO` can be `repo-name` (uses `ORG_NAME` as owner) or `owner/repo-name`. |
| `repos` | `SCOPE=repos` + `REPOS` | Multiple repositories. `REPOS` is comma- or newline-separated; each item is `repo-name` or `owner/repo-name`. Use `ORG_NAME` as default owner when only names are given. |
| `topic` | `SCOPE=topic` + `REPO_TOPIC` (or `TOPIC`) | All org repos that have the given GitHub topic (tag). Requires `ORG_NAME` and `REPO_TOPIC`. |

## Requirements

- **Python 3.9+** (stdlib only: `os`, `json`, `urllib.request`, `re`, `argparse`, `datetime`, `fnmatch`).
- **GitHub PAT**: A token with `repo` (and `read:org` if scanning an org). For **artifact** cleanup: repo is enough. For **package** cleanup (org-level): add `read:packages` and `delete:packages`; store as a secret (e.g. `JANITOR_BOT_PAT`).

## Inputs (action.yml) → Environment variables (janitor.py)

The action passes its inputs into the script as environment variables. You can also run `janitor.py` locally or in another CI system by setting these env vars.

| Action input             | Env variable           | Type   | Default                      | Description |
|--------------------------|------------------------|--------|------------------------------|-------------|
| `mode`                   | —                      | string | `scan`                       | `scan` or `cleanup`. |
| `gh_token`               | `GH_TOKEN`             | string | *required*                  | GitHub PAT. |
| `scope`                  | `SCOPE`                | string | `org`                        | `org`, `repo`, `repos`, or `topic`. |
| `org_name`               | `ORG_NAME`             | string | `github.repository_owner`    | Org/owner. Required for `org`/`topic`; default owner for `repo`/`repos` when repo is just a name. |
| `repo`                   | `REPO`                 | string | —                            | Single repo: name or `owner/repo`. Used when `scope=repo`. |
| `repos`                  | `REPOS`                | string | —                            | Multiple repos: comma or newline separated. Used when `scope=repos`. |
| `repo_topic`             | `REPO_TOPIC` or `TOPIC`| string | —                            | GitHub topic (tag). Used when `scope=topic`. |
| `branch_stale_days`      | `BRANCH_STALE_DAYS`    | int    | `45`                         | Branches older than this (days) are stale. |
| `branch_exclude_regex`   | `BRANCH_EXCLUDE_REGEX` | string | `^(main\|master\|develop)$` | Regex for branch names to never touch. |
| `branch_include_pattern` | `BRANCH_INCLUDE_PATTERN` | string | `*` | **Glob**: only consider branches matching this (e.g. `feature/*`). `*` = all. |
| —                        | *(built-in)*           | —      | —                            | **Protected branches** are always skipped (never touched). |
| `branch_protect_pr`      | `BRANCH_PROTECT_PR`    | bool   | `true`                       | Skip branches that have an open PR. |
| `pr_stale_days`          | `PR_STALE_DAYS`        | int    | `30`                         | PRs older than this (days) are stale. |
| `pr_exclude_labels`     | `PR_EXCLUDE_LABELS`    | string | `pinned`                     | Comma-separated labels; PRs with any are excluded. |
| `pkg_keep_count`         | `PKG_KEEP_COUNT`       | int    | `5`                          | Number of package versions to keep. |
| `dry_run`                | `DRY_RUN`              | bool   | `true`                       | If true, no destructive actions. |
| `batch_delay_seconds`    | `BATCH_DELAY_SECONDS`  | float  | `0`                          | Optional delay between repos to reduce API burst. |
| `cleanup_branches`       | `CLEANUP_BRANCHES`     | bool   | `true`                       | When true, run branch scan (report only). |
| `cleanup_artifacts`      | `CLEANUP_ARTIFACTS`    | bool   | `false`                      | When true, run artifact scan/cleanup (filtered by `artifact_name_pattern`). |
| `artifact_name_pattern`  | `ARTIFACT_NAME_PATTERN`| string | `*`                          | **Glob** for artifact names (e.g. `plan-*`). `*` = all. |
| `artifact_stale_days`    | `ARTIFACT_STALE_DAYS`  | int    | `30`                         | Artifacts older than this (days) are stale. |
| `artifact_keep_count`    | `ARTIFACT_KEEP_COUNT`  | int    | `0`                          | Keep at least this many most recent matching artifacts (0 = use only stale_days). |
| `cleanup_prs`            | `CLEANUP_PRS`          | bool   | `false`                      | When true, run PR scan/cleanup (close stale PRs). |
| `pr_head_ref_pattern`    | `PR_HEAD_REF_PATTERN`  | string | `*`                          | **Glob** for PR head ref (branch) to consider (e.g. `feature/*`). `*` = all. |
| `cleanup_packages`       | `CLEANUP_PACKAGES`     | bool   | `false`                      | When true, run package version cleanup (org-level). |
| `pkg_name_pattern`       | `PKG_NAME_PATTERN`     | string | `*`                          | **Glob** for package names (e.g. `my-app-*`). `*` = all. |
| `pkg_type`               | `PKG_TYPE`             | string | `container`                   | Package type for org packages (`container`, `npm`, etc.). |

The script converts string inputs to the correct types and compiles `BRANCH_EXCLUDE_REGEX` for performance.

## Enable only what you need (branches, PRs, artifacts, packages)

You can run **only one** cleanup type or **any combination**. Set the corresponding `cleanup_*` flags and use the **pattern** for that type to restrict by name/key.

| Type      | Enable with           | Pattern input              | Description |
|-----------|-----------------------|----------------------------|-------------|
| Branches  | `cleanup_branches: true`  | `branch_include_pattern`   | Only branches matching glob (e.g. `feature/*`). Report only (no branch delete). |
| PRs       | `cleanup_prs: true`       | `pr_head_ref_pattern`      | Only PRs whose head ref matches (e.g. `release-*`). Closes stale PRs. |
| Artifacts | `cleanup_artifacts: true` | `artifact_name_pattern`    | Only artifacts whose name matches (e.g. `plan-*`). Deletes old artifacts. |
| Packages  | `cleanup_packages: true`  | `pkg_name_pattern`         | Only packages whose name matches (e.g. `my-app-*`). Deletes old versions (org-level). |

**Example: only artifacts** (pattern `plan-*`), keep latest 5, delete older than 14 days:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    mode: cleanup
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
    scope: repo
    repo: ${{ github.repository }}
    cleanup_branches: false
    cleanup_prs: false
    cleanup_packages: false
    cleanup_artifacts: true
    artifact_name_pattern: 'plan-*'
    artifact_stale_days: 14
    artifact_keep_count: 5
    dry_run: false
```

**Example: only PRs** (head ref pattern `feature/*`), close PRs older than 30 days:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    mode: cleanup
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
    scope: repo
    repo: ${{ github.repository }}
    cleanup_branches: false
    cleanup_artifacts: false
    cleanup_packages: false
    cleanup_prs: true
    pr_head_ref_pattern: 'feature/*'
    pr_stale_days: 30
    dry_run: false
```

**Example: only branches** (include pattern `release-*`), scan and report:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    mode: scan
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
    scope: repo
    repo: ${{ github.repository }}
    cleanup_branches: true
    cleanup_artifacts: false
    cleanup_prs: false
    cleanup_packages: false
    branch_include_pattern: 'release-*'
```

**Example: only packages** (org-level, name pattern `my-service-*`), keep 5 versions:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    mode: cleanup
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
    scope: org
    org_name: my-org
    cleanup_branches: false
    cleanup_artifacts: false
    cleanup_prs: false
    cleanup_packages: true
    pkg_name_pattern: 'my-service-*'
    pkg_type: container
    dry_run: false
```

Use `*` for any pattern to mean "all" for that type. You can enable two or more types in one run (e.g. artifacts + PRs) and set each pattern independently.

## Usage

### 1. Use the action in a workflow

Example: run on schedule and on manual dispatch with UI inputs.

```yaml
name: Janitor
on:
  workflow_dispatch:
    inputs:
      mode:
        description: 'Mode'
        required: true
        default: scan
        type: choice
        options:
          - scan
          - cleanup
      branch_days:
        description: 'Branch stale (days)'
        required: false
        default: 45
        type: number
      exclude_pattern:
        description: 'Branch exclude regex'
        required: false
        default: '^(main|master|develop)$'
        type: string
      pr_days:
        description: 'PR stale (days)'
        required: false
        default: 30
        type: number
  schedule:
    - cron: '0 2 * * 0'   # weekly, 02:00 UTC

jobs:
  janitor:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout (optional; for local action)
        uses: actions/checkout@v4
        if: github.event_name == 'workflow_dispatch'

      - name: Run Janitor Bot
        uses: ./.github/actions/janitor-bot   # or your repo path
        with:
          mode: ${{ github.event.inputs.mode || 'scan' }}
          gh_token: ${{ secrets.JANITOR_BOT_PAT }}
          org_name: ${{ github.repository_owner }}
          branch_stale_days: ${{ github.event.inputs.branch_days || 45 }}
          branch_exclude_regex: ${{ github.event.inputs.exclude_pattern || '^(main|master|develop)$' }}
          pr_stale_days: ${{ github.event.inputs.pr_days || 30 }}
          # optional: pr_exclude_labels, pkg_keep_count, dry_run

      - name: Upload report
        uses: actions/upload-artifact@v4
        if: github.event.inputs.mode != 'cleanup'
        with:
          name: janitor-report
          path: janitor_report.md
```

**Single repo** (e.g. current repo):

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    scope: repo
    repo: ${{ github.repository }}   # owner/repo
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
```

**Multiple repos**:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    scope: repos
    repos: 'repo-a, repo-b, my-org/repo-c'
    org_name: ${{ github.repository_owner }}
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
```

**Org repos with a topic**:

```yaml
- uses: ./.github/actions/janitor-bot
  with:
    scope: topic
    org_name: my-org
    repo_topic: managed
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
```

For a **reusable workflow** or **another repo**, use the action by path or `owner/repo@ref`:

```yaml
- uses: owner/repo/.github/actions/janitor-bot@main
  with:
    mode: scan
    gh_token: ${{ secrets.JANITOR_BOT_PAT }}
    org_name: my-org
```

### 2. Run the script locally (no JSON file)

Set env vars and run. Examples:

**Entire org (default):**

```bash
export GH_TOKEN="ghp_..."
export ORG_NAME="my-org"
python3 path/to/janitor.py --mode scan
```

**Single repo** (`REPO` = name or `owner/repo`):

```bash
export GH_TOKEN="ghp_..."
export SCOPE=repo
export REPO="my-org/my-repo"
# or: export ORG_NAME=my-org && export REPO=my-repo
python3 path/to/janitor.py --mode scan
```

**Multiple repos** (comma or newline):

```bash
export SCOPE=repos
export REPOS="repo-a, repo-b, other/repo-c"
export ORG_NAME="my-org"
python3 path/to/janitor.py --mode scan
```

**Org repos with topic:**

```bash
export SCOPE=topic
export ORG_NAME="my-org"
export REPO_TOPIC="managed"
python3 path/to/janitor.py --mode scan
```

Defaults apply when a variable is missing (e.g. scope=org, 45 for branches, 30 for PRs). The report is written to `janitor_report.md` in the current directory.

### 3. Report output

`janitor_report.md` includes:

- **Thresholds used**: Scope, all cleanup_* flags, branch/PR/package/artifact patterns and settings, dry run.
- **Stale branches**: Table of repo, branch, owner, days stale (when `cleanup_branches` is enabled).
- **Artifacts**: Table of repo, artifact name, ID, size, days stale (when `cleanup_artifacts` is enabled).
- **Pull requests**: Table of repo, PR number, title, head ref, days stale (when `cleanup_prs` is enabled).
- **Packages**: Table of org, package type, name, version ID, days stale (when `cleanup_packages` is enabled).

No JSON config file is required; everything is driven by environment variables (and in GitHub Actions, by mapping workflow inputs to those env vars).

## Security

- Store the PAT in **GitHub Secrets** (e.g. `JANITOR_BOT_PAT`). Never commit it.
- Use a fine-grained or classic PAT with minimal scope: `repo` (and `read:org` if scanning an org).
- Prefer `scan` and review the report before enabling `cleanup` in production.

## License

Same as the platform repo.
