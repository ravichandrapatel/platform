# Git Change Detector

![Git Path Filter logo](logo.png)

A robust, Python-based GitHub Composite Action for detecting file changes in a repository. It allows you to define groups of file patterns (using glob syntax) and determines if any files in those groups have changed between two git references.

This action is designed to be **reusable**, meaning you can host it in a central "GitOps" or "DevOps" repository and reference it from any other repository in your organization.

## 🚀 Features

-   **Python-powered**: Uses Python's `fnmatch` for reliable pattern matching.
-   **Git Integration**: Automatically handles `git fetch` and `git diff` logic to ensure accurate comparisons.
-   **Flexible Filtering**: Supports inclusion and exclusion (`!`) patterns.
-   **JSON Outputs**: Provides structured JSON output for easy consumption in workflows.
-   **Monorepo Friendly**: Ideal for selectively running CI jobs based on modified paths.

## ⚙️ Inputs


| Input | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `source_branch` | The source reference to check for changes (e.g., `github.head_ref` for PRs). | **Yes** | N/A |
| `base_ref_branch` | The base reference to compare against (e.g., `github.base_ref` or `main`). | **Yes** | N/A |
| `pattern_filter` | A YAML-formatted string defining your file groups and patterns. | **Yes** | N/A |
| `github_token` | GitHub token used to fetch git history. | No | `${{ github.token }}` |

## 📤 Outputs

| Output | Description |
| :--- | :--- |
| `changes` | A JSON array of keys (group names) that have changes. Example: `["backend", "docs"]` |
| `changes_json` | A comprehensive JSON object containing boolean flags and file lists for every group. |

### Output Structure (`changes_json`)

```json
{
  "backend": {
    "has_changes": true,
    "files": ["src/api/main.py", "requirements.txt"]
  },
  "frontend": {
    "has_changes": false,
    "files": []
  },
  "_unmatched": {
    "has_changes": true,
    "files": ["readme.md"]
  }
}
```

## Example Usage

The following example demonstrates how to use this action and then run specific jobs based on which group of files has changed. It uses the `fromJSON()` function to parse the output and `needs` context to pass the data between jobs.

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  pull_request:
    branches:
      - main

jobs:
  # Job 1: Run the change detection action
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      changes: ${{ steps.changes.outputs.changes }}
      changes_json: ${{ steps.changes.outputs.changes_json }}
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Required to fetch git history for diffing

      - name: Detect changes based on YAML filter
        id: changes
        uses: ./platform/actions/git-path-filter
        with:
          source_branch: ${{ github.head_ref }}
          base_ref_branch: ${{ github.base_ref }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          pattern_filter: |
            backend:
              - 'src/api/**/*.py'
              - 'tests/backend/'
              - 'requirements.txt'
            frontend:
              - 'src/webapp/**/*.js'
              - 'tests/frontend/'
              - 'package.json'

  # Job 2: Run backend tests only if backend files changed
  run-backend-tests:
    runs-on: ubuntu-latest
    needs: detect-changes # Depends on the first job
    # Use fromJSON() to parse the output and access the 'backend' group results
    if: needs.detect-changes.outputs.changes_json != '' && fromJSON(needs.detect-changes.outputs.changes_json).backend.has_changes
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Run Backend Tests
        run: |
          echo "Backend changes detected. Running tests..."
          # Add your actual backend test commands here
          
  # Job 3: Run frontend tests only if frontend files changed
  run-frontend-tests:
    runs-on: ubuntu-latest
    needs: detect-changes
    if: needs.detect-changes.outputs.changes_json != '' && fromJSON(needs.detect-changes.outputs.changes_json).frontend.has_changes
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Run Frontend Tests
        run: |
          echo "Frontend changes detected. Running tests..."
          # Add your actual frontend test commands here
```
