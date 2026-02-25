# Platform Component Manager workflow

The **Platform Component Manager** workflow lets you **promote** or **rollback** version tags for platform components. It is intended for **reusable actions** (and optionally other component paths you want to version the same way). It uses **immutable** full-version tags and **movable** major-version “stable” tags so consumers can pin to a version or follow a major line.

**Important:** A Git tag always points to a **commit** (the entire repo at that ref). The **component path** is only used in the **tag name** (e.g. `platform/actions/my-action/1.2.0`) so you can have multiple components with independent version tags on the same repo. When a consumer uses `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`, GitHub resolves the tag to that commit and runs the action from its path at that commit.

### I want a tag to contain only the action’s code, not the whole repo

**Git does not support path-scoped tags.** A tag always points to one commit. You can, however, make that commit’s **tree** contain only the action’s code by using a **temporary branch** created with `git subtree split`: the branch tip has only the action’s files (at repo root); you tag that branch, then delete the branch. The tag then points to a commit whose tree is only that action.

**Options:**

| Approach | Tag contains | How |
|----------|----------------|-----|
| **Monorepo** | Whole repo at that commit. | Run workflow with **tag_content = monorepo** (default). Consumers: `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`. |
| **Subtree (temp branch)** | Only the action’s code; **folder path preserved** (e.g. `platform/actions/my-action/`). | Run workflow with **tag_content = subtree**. The workflow creates an orphan branch with only that path in the tree, tags it, then deletes the branch. Consumers use the **same path** as in the monorepo: `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`. |
| **One repo per action** | Only that action’s code. | Move the action to its own repository and tag that repo. Consumers: `uses: org/my-action@v1.2.0`. |

**Subtree in practice:** Choose **tag_content = subtree** when promoting. The tag will point to a commit whose tree contains **only** the component path (e.g. `platform/actions/my-action/` with its files). The folder name is preserved, so consumers use the same path as for monorepo: `uses: YOUR_ORG/REPO/platform/actions/my-action@platform/actions/my-action/1.2.0`. Rollback works the same (stable tag is moved to the existing full-version tag).

---

## Scope: actions vs reusable workflows

| What | Where it lives | How to release / use a tagged version |
|------|----------------|----------------------------------------|
| **Reusable actions** | Any path (e.g. `platform/actions/my-action/`). | Use this workflow: promote/rollback with `component_path` = action folder. Consumers: `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`. |
| **Reusable workflows** | **Source:** `workflows/<name>/` or `platform/workflows/<name>/` (folder), or the same with a single `.yml` file. **Published:** on promote, files are **copied** to **`.github/workflows/`** (GitHub only runs workflows from there). | Run this workflow with `component_path` = `workflows/<name>` or `platform/workflows/<name>` (e.g. `platform/workflows/compliance`). On **promote**, the workflow copies that path’s files into `.github/workflows/`, commits and pushes, then creates tags `{component_path}/{version}` and `{component_path}/v{major}`. Callers: `uses: org/repo/.github/workflows/<name>.yml@workflows/compliance/1.0.0`. Rollback works the same (stable tag moved to existing full-version tag). |

---

## Overview

| Concept | Meaning |
|--------|--------|
| **Component path** | Folder or path under the repo: e.g. `platform/actions/owasp-dependency-check`, or `workflows/compliance` (workflow folder/file). Used as the **tag name prefix**; the tag points to a **commit** (for workflows, after copying to `.github/workflows/`). |
| **Full version tag** | Tag like `platform/actions/my-action/1.2.0`. Points to a **single commit** (whole repo) and is **never moved**. |
| **Stable tag** | Tag like `platform/actions/my-action/v1`. Points to the “current” release for that major version and is **moved** on promote or rollback. |

- **Promote:** At current `HEAD`, create the full-version tag and move the stable tag to `HEAD`.
- **Rollback:** Move the stable tag back to the commit of an **existing** full-version tag (no new commit).

---

## When to use it

- **Promote:** You’ve merged changes to a component and want to release a new version (e.g. `1.2.0`) and update the stable pointer (e.g. `v1` → latest `1.2.0`).
- **Rollback:** A release is bad and you want the stable tag (e.g. `v1`) to point again at an older full version (e.g. `1.1.0`) without changing code.

---

## How to run it

1. In the repo, go to **Actions** → **Platform Component Manager** → **Run workflow**.
2. Fill the inputs:
   - **component_path** (required): Path to the component, relative to repo root.  
     Examples: `platform/actions/owasp-dependency-check`, `workflows/compliance`, `platform/workflows/compliance` (folder or single file).
   - **mode** (required): `promote` or `rollback`.
   - **version** (required): Target version for the **full** tag, e.g. `1.2.0` (promote) or the version you want to roll back to, e.g. `1.1.0` (rollback).
3. Run the workflow on the branch you want (usually `main` or `release/*`). For **promote**, the workflow uses the commit that is `HEAD` of that branch at run time.

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `component_path` | Yes | Path of the component: action folder (e.g. `platform/actions/owasp-dependency-check`) or workflow path (e.g. `workflows/compliance` folder or `workflows/compliance.yml`). Defines the tag prefix. For **subtree**, the path must exist. For **workflows**, on promote the workflow copies files to `.github/workflows/` then tags. |
| `mode` | Yes | `promote` – create/move tags. `rollback` – move stable tag to an existing full-version tag. |
| `version` | Yes | Semantic version for the **full** tag (e.g. `1.2.0`). On promote this is the new version; on rollback this is the version the stable tag will point to. |
| `tag_content` | No | **monorepo** (default) – tag points to current `HEAD` (whole repo). **subtree** – tag points to a commit that contains only the component path (folder structure preserved, e.g. `platform/actions/my-action/`). Use **subtree** if you want the tag to contain only that action; consumers use the same path (e.g. `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`). |

---

## Tag naming

- **Full (immutable) tag:** `{component_path}/{version}`  
  Examples: `platform/actions/my-action/1.2.0`, `workflows/compliance/1.0.0`.
- **Stable (movable) tag:** `{component_path}/v{major}`  
  Examples: `platform/actions/my-action/v1`, `workflows/compliance/v1`.

So for `component_path = platform/actions/my-action` and `version = 1.2.0`:

- Full tag: `platform/actions/my-action/1.2.0`
- Stable tag: `platform/actions/my-action/v1`

---

## Promote (mode: promote)

1. **Workflows only:** If `component_path` is `workflows/<name>` (folder or file), the workflow first copies all files from that path into **`.github/workflows/`** (e.g. `workflows/compliance/compliance.yml` → `.github/workflows/compliance.yml`), then commits and pushes. The rest of the run uses this new commit as the ref to tag.
2. Workflow runs at **current `HEAD`** of the selected branch (after the workflow publish step for workflows).
3. Creates tag **`{component_path}/{version}`** at that commit (e.g. `platform/actions/my-action/1.2.0`, or `workflows/compliance/1.0.0`). This tag is **immutable** and never moved.
4. Creates or updates tag **`{component_path}/v{major}`** to point at the same commit. This is the **stable** pointer.
5. Pushes both tags. The stable tag is pushed with `--force` because it is updated in place.

Use this when you are releasing a new version and want that version to become the current “stable” for that major line.

---

## Rollback (mode: rollback)

1. Does **not** create a new commit or new full-version tag.
2. Moves the **stable** tag `{component_path}/v{major}` so it points to the same commit as the **existing** full-version tag `{component_path}/{version}`.
3. Pushes the stable tag with `--force`.

**Requirement:** The full-version tag you give in `version` must already exist (from a previous promote). Example: to rollback `v1` to `1.1.0`, the tag `platform/actions/my-action/1.1.0` must already exist.

Use this when the current stable release is bad and you want consumers using `v1` (or `v2`, etc.) to get the previous good version again.

---

## First release, then rollback (example)

**Subtree flow:** You release the action for the first time, then release a new version, then rollback to the previous tag when the new one has issues.

| Step | What you do | Result |
|------|-------------|--------|
| **1. First release** | Run workflow: `component_path` = `platform/actions/my-action`, `mode` = **promote**, `version` = `1.0.0`, `tag_content` = **subtree**. | Tag `platform/actions/my-action/1.0.0` and stable tag `platform/actions/my-action/v1` both point to a commit that contains only that folder. Consumers using `@platform/actions/my-action/v1` get 1.0.0. |
| **2. New release** | Run workflow: same path, **promote**, `version` = `1.1.0`, `tag_content` = **subtree**. | Tag `platform/actions/my-action/1.1.0` is created (only that folder). Stable tag `v1` is **moved** to point to 1.1.0. Consumers using `@v1` now get 1.1.0. Tag `1.0.0` is unchanged. |
| **3. Rollback to previous** | Run workflow: same path, **rollback**, `version` = `1.0.0`. | No new commit or tag. Stable tag `v1` is **moved** to point to the same commit as **existing** tag `1.0.0`. Consumers using `@v1` get 1.0.0 again. Tags `1.0.0` and `1.1.0` are unchanged. |

You do **not** need to recreate the previous subtree: the full-version tag (e.g. `1.0.0`) already points to that commit. Rollback only re-points the **stable** tag (`v1`) to that existing tag.

---

## Permissions and secrets

- The workflow needs **Contents: write** to create/update tags and push them.
- It uses **`GITHUB_TOKEN`** for `git push`. If your branch or tag rules require a PAT, configure a secret (e.g. `COMMIT_TOKEN`) and use it in the “Execute Tag Flip” step instead of `GITHUB_TOKEN`.

---

## Using these tags in other repos

Consumers can pin to a **full** version (immutable) or to the **stable** major (moves on promote/rollback):

- **Immutable (recommended for production):**  
  `uses: org/repo/platform/actions/my-action@platform/actions/my-action/1.2.0`
- **Stable major (auto-updates on promote, can rollback):**  
  `uses: org/repo/platform/actions/my-action@platform/actions/my-action/v1`

---

## Example: promote then rollback

1. **Promote 1.2.0**  
   - Branch: `main`, `HEAD` = commit A.  
   - Inputs: `component_path = platform/actions/my-action`, `mode = promote`, `version = 1.2.0`.  
   - Result:  
     - Tag `platform/actions/my-action/1.2.0` → commit A.  
     - Tag `platform/actions/my-action/v1` → commit A.

2. **Rollback to 1.1.0**  
   - Assume `platform/actions/my-action/1.1.0` already exists at commit B.  
   - Inputs: `component_path = platform/actions/my-action`, `mode = rollback`, `version = 1.1.0`.  
   - Result:  
     - Tag `platform/actions/my-action/v1` → commit B (same as `1.1.0`).  
     - Tag `platform/actions/my-action/1.2.0` is unchanged.

Consumers pinning to `@platform/actions/my-action/v1` will now resolve to `1.1.0` (commit B) until you promote again.

---

## How to release tagged versions (summary)

| Component type | Where it lives | How to release a version |
|----------------|----------------|---------------------------|
| **Action** | e.g. `platform/actions/my-action/` | Run **Platform Component Manager** → `component_path` = `platform/actions/my-action`, `mode` = promote, `version` = `1.2.0`. Use branch = `main` (or your release branch). |
| **Reusable workflow** | **Source:** `workflows/<name>/` or `platform/workflows/<name>/` (or single file) | Run **Platform Component Manager** → `component_path` = `workflows/<name>` or `platform/workflows/<name>`, `mode` = promote, `version` = `1.0.0`. The workflow copies files to `.github/workflows/`, commits and pushes, then creates tags `{component_path}/{version}` and `{component_path}/v{major}`. Callers: `uses: org/repo/.github/workflows/<name>.yml@workflows/<name>/1.0.0` (or same with `platform/workflows/<name>/1.0.0`). |

Remember: every Git tag points to a **commit** (the whole repo). The component path in the tag name only identifies *which* component’s version the tag represents; it does not limit the ref to a folder.
