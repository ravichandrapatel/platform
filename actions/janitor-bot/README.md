# Janitor Bot Action

Scan or cleanup **stale branches** (and optionally PRs) for **one repo**, **multiple repos**, **entire org**, or **repos with a topic (tag)**. Configuration is **100% environment variables**—no JSON config file. Ideal for use with `workflow_dispatch` so you can change scope and thresholds from the "Run workflow" UI.

## Features

- **Scope**: Run against a single repo, a list of repos, all repos in an org, or all org repos that have a given GitHub **topic** (tag).
- **Branch scan**: Finds branches older than a configurable number of days, with optional regex exclusion and "skip if open PR" protection. **Protected branches are never touched** (skipped in both scan and cleanup).
- **Config via env**: All settings come from environment variables (e.g. `SCOPE`, `REPO`, `REPOS`, `REPO_TOPIC`, `BRANCH_STALE_DAYS`), which you map from workflow inputs in YAML.
- **Markdown report**: Writes `janitor_report.md` with **explicit thresholds and scope** used for the run and a table of stale branches (and later PRs/packages).
- **API throttling**: Uses a `RateLimiter` and `GitHubApiClient` that read `X-RateLimit-Remaining` / `X-RateLimit-Reset` and, on 403/429, retry with backoff (including `Retry-After`). Repos are processed in a batch-friendly way with an optional delay between repos (`BATCH_DELAY_SECONDS`).

## Scope (what to scan)

| Scope   | Env / input      | Description |
|---------|------------------|-------------|
| `org`   | `SCOPE=org`      | All repositories in the organization (default). Requires `ORG_NAME`. |
| `repo`  | `SCOPE=repo` + `REPO` | Single repository. `REPO` can be `repo-name` (uses `ORG_NAME` as owner) or `owner/repo-name`. |
| `repos` | `SCOPE=repos` + `REPOS` | Multiple repositories. `REPOS` is comma- or newline-separated; each item is `repo-name` or `owner/repo-name`. Use `ORG_NAME` as default owner when only names are given. |
| `topic` | `SCOPE=topic` + `REPO_TOPIC` (or `TOPIC`) | All org repos that have the given GitHub topic (tag). Requires `ORG_NAME` and `REPO_TOPIC`. |

## Requirements

- **Python 3.9+** (stdlib only: `os`, `json`, `urllib.request`, `re`, `argparse`, `datetime`).
- **GitHub PAT**: A token with `repo` (and `read:org` if scanning an org) scope; store it as a secret (e.g. `JANITOR_BOT_PAT`).

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
| —                        | *(built-in)*           | —      | —                            | **Protected branches** are always skipped (never touched). |
| `branch_protect_pr`      | `BRANCH_PROTECT_PR`    | bool   | `true`                       | Skip branches that have an open PR. |
| `pr_stale_days`          | `PR_STALE_DAYS`        | int    | `30`                         | PRs older than this (days) are stale. |
| `pr_exclude_labels`      | `PR_EXCLUDE_LABELS`    | string | `pinned`                     | Comma-separated labels; PRs with any are excluded. |
| `pkg_keep_count`         | `PKG_KEEP_COUNT`       | int    | `5`                          | Number of package versions to keep. |
| `dry_run`                | `DRY_RUN`              | bool   | `true`                       | If true, no destructive actions. |
| `batch_delay_seconds`    | `BATCH_DELAY_SECONDS`  | float  | `0`                          | Optional delay between repos to reduce API burst. |

The script converts string inputs to the correct types (e.g. `'45'` → `45`) and compiles `BRANCH_EXCLUDE_REGEX` with `re.compile()` for performance.

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

- **Thresholds used**: Scope, branch stale days, branch exclude regex, PR stale days, PR exclude labels, package keep count, dry run.
- **Stale branches**: Table of repo (owner/repo), branch, owner, days stale.

No JSON config file is required; everything is driven by environment variables (and in GitHub Actions, by mapping workflow inputs to those env vars).

## Security

- Store the PAT in **GitHub Secrets** (e.g. `JANITOR_BOT_PAT`). Never commit it.
- Use a fine-grained or classic PAT with minimal scope: `repo` (and `read:org` if scanning an org).
- Prefer `scan` and review the report before enabling `cleanup` in production.

## License

Same as the platform repo.
