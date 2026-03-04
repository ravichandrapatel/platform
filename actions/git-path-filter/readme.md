# Git Path Filter

![Git Path Filter logo](logo.png)

A robust, Python-based GitHub Composite Action for detecting file changes in a repository. It compares two git refs (branch, tag, or SHA) and reports which changed files match your YAML-defined pattern groups—so you can run jobs only when relevant paths change.

This action is **reusable**: host it in a central repo and reference it from any workflow (same org or `actions/checkout` + path).

## Features

-   **Ref-agnostic**: Works with branches, tags, or SHAs (no `origin/` prefix). Supports `pull_request`, `push`, and `workflow_dispatch`.
-   **Git**: Fetches with `git fetch origin <ref> --depth=1 --no-tags`; uses `git diff --name-status` for change types (A/M/D). **Zero-SHA guard**: when base is all zeros (new-branch push), lists all files in the source ref.
-   **Globbing**: Via [wcmatch](https://pypi.org/project/wcmatch/): `**` (recursive), `*`, `?`, `[...]`, `[!a-z]`, brace expansion `{a,b}`; robust edge cases.
-   **Negation**: `!` prefix with **last-match-wins** (sequential override).
-   **Status**: Git status preserved where useful: `R` (rename), `C` (copy), `T` (type change → M); others normalized to `A`/`M`/`D`.
-   **Change types**: Optional filter by status (`A`, `M`, `D`).
-   **Working directory**: Optional base path; only paths under it are considered; patterns are matched relative to it.
-   **Outputs**: `has_changes`, `files`, `every_file_matches` per group; `_unmatched` for files not in any group.
-   **Dependencies**: PyYAML, wcmatch (pinned in `requirements.txt`). CLI: `--debug` for verbose include/exclude logging.

## Inputs

| Input | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `source_branch` | Source/head ref (branch name, tag, or SHA). | **Yes** | — |
| `base_ref_branch` | Base ref to compare against (no `origin/` prefix). | **Yes** | — |
| `pattern_filter` | YAML string: key → list of globs; `!` = exclude (last match wins). | **Yes** | — |
| `github_token` | Token for `git fetch`. | No | `${{ github.token }}` |
| `change_types` | Comma-separated `A,M,D` to consider only those statuses. | No | `''` |
| `debug` | `true` to log include/exclude reason per file. | No | `false` |
| `working_directory` | Base path; only paths under this dir are considered; matching is relative to it. | No | `''` |

## Outputs

| Output | Description |
| :--- | :--- |
| `changes` | JSON array of group keys that have changes. e.g. `["backend", "docs"]` |
| `changes_json` | Full object: per group `has_changes`, `files`, `every_file_matches`; plus `_unmatched`. |

### Output structure (`changes_json`)

Paths are POSIX (forward slashes).

```json
{
  "backend": {
    "has_changes": true,
    "files": ["src/api/main.py", "requirements.txt"],
    "every_file_matches": false
  },
  "frontend": {
    "has_changes": false,
    "files": [],
    "every_file_matches": false
  },
  "_unmatched": {
    "has_changes": true,
    "files": ["readme.md"],
    "every_file_matches": false
  }
}
```

---

## How to use in all scenarios

Use a single **detect-changes** job and set **source** and **base** refs based on the event. Then pass those refs into the action. Always use **checkout with `fetch-depth: 0`** so the workflow has history for diffing.

### 1. Pull request (PR to target branch)

Compare the **PR head** to the **PR base branch**.

| Ref | Value |
| --- | ----- |
| Source | `github.head_ref` (branch name of the PR head) |
| Base | `github.base_ref` (branch the PR targets, e.g. `main`) |

```yaml
on:
  pull_request:
    branches: [main]

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changes (git-path-filter)
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ github.head_ref }}
          base_ref_branch: ${{ github.base_ref }}
          pattern_filter: |
            backend:
              - 'src/**/*.py'
            frontend:
              - 'src/**/*.js'
```

### 2. Push (e.g. merge to default branch)

Compare the **merge commit** (current SHA) to the **previous commit** or the default branch (e.g. for the first push to a new branch, or when `before` is missing).

| Ref | Value |
| --- | ----- |
| Source | `github.sha` (commit that triggered the run) |
| Base | `github.event.before` if present, else `github.event.repository.default_branch` |

```yaml
on:
  push:
    branches: [main]

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set refs for push
        id: refs
        run: |
          echo "source=${{ github.sha }}" >> $GITHUB_OUTPUT
          echo "base=${{ github.event.before || github.event.repository.default_branch }}" >> $GITHUB_OUTPUT

      - name: Detect changes (git-path-filter)
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ steps.refs.outputs.source }}
          base_ref_branch: ${{ steps.refs.outputs.base }}
          pattern_filter: |
            app:
              - '**/*.tfvars'
```

### 3. Manual run (`workflow_dispatch`)

Compare the **current branch** (ref name) to the **default branch**. Use when running the workflow manually (e.g. on a feature branch before opening a PR).

| Ref | Value |
| --- | ----- |
| Source | `github.ref_name` (branch or tag that was checked out) |
| Base | `github.event.repository.default_branch` (e.g. `main`) |

```yaml
on:
  workflow_dispatch:

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changes (git-path-filter)
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ github.ref_name }}
          base_ref_branch: ${{ github.event.repository.default_branch }}
          pattern_filter: |
            tfvars:
              - '**/*.tfvars'
```

### 4. One workflow: PR, push, and manual

Use one job and set source/base in a previous step from the event name.

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set refs for detection
        id: refs
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "source=${{ github.ref_name }}" >> $GITHUB_OUTPUT
            echo "base=${{ github.event.repository.default_branch }}" >> $GITHUB_OUTPUT
          elif [ "${{ github.event_name }}" = "pull_request" ]; then
            echo "source=${{ github.head_ref }}" >> $GITHUB_OUTPUT
            echo "base=${{ github.base_ref }}" >> $GITHUB_OUTPUT
          else
            echo "source=${{ github.sha }}" >> $GITHUB_OUTPUT
            echo "base=${{ github.event.before || github.event.repository.default_branch }}" >> $GITHUB_OUTPUT
          fi

      - name: Detect changes (git-path-filter)
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ steps.refs.outputs.source }}
          base_ref_branch: ${{ steps.refs.outputs.base }}
          pattern_filter: |
            tfvars:
              - '**/*.tfvars'
```

### 5. New-branch push (zero base)

When the base ref is the **zero SHA** (`0{40}`), the action does not run a diff; it lists **all files** in the source ref (e.g. new branch). Your “Set refs” step can pass `github.event.before` as base; GitHub may send the zero SHA for new-branch pushes.

### 6. Downstream jobs: run only when a group has changes

Use `changes_json` and `fromJSON()` in the job `if` condition:

```yaml
  run-backend-tests:
    runs-on: ubuntu-latest
    needs: detect-changes
    if: needs.detect-changes.outputs.changes_json != '' && fromJSON(needs.detect-changes.outputs.changes_json).backend.has_changes
    steps:
      - uses: actions/checkout@v4
      - run: ./run-backend-tests.sh
```

Optional: filter by change type (e.g. only added or modified):

```yaml
      - name: Detect changes (git-path-filter)
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ steps.refs.outputs.source }}
          base_ref_branch: ${{ steps.refs.outputs.base }}
          change_types: 'A,M'
          pattern_filter: |
            backend:
              - 'src/**/*.py'
```

---

## Full example: monorepo backend/frontend

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Detect changes
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ github.head_ref }}
          base_ref_branch: ${{ github.base_ref }}
          pattern_filter: |
            backend:
              - 'src/api/**/*.py'
              - 'requirements.txt'
            frontend:
              - 'src/webapp/**/*.js'
              - 'package.json'

  run-backend-tests:
    runs-on: ubuntu-latest
    needs: detect-changes
    if: needs.detect-changes.outputs.changes_json != '' && fromJSON(needs.detect-changes.outputs.changes_json).backend.has_changes
    steps:
      - uses: actions/checkout@v4
      - run: echo "Backend tests..."

  run-frontend-tests:
    runs-on: ubuntu-latest
    needs: detect-changes
    if: needs.detect-changes.outputs.changes_json != '' && fromJSON(needs.detect-changes.outputs.changes_json).frontend.has_changes
    steps:
      - uses: actions/checkout@v4
      - run: echo "Frontend tests..."
```
