# Platform Component Manager workflow

The **Platform Component Manager** workflow lets you **promote** or **rollback** version tags for platform components (e.g. `platform/actions/my-action`, `platform/images/my-image`) using a manual trigger. It uses **immutable** full-version tags and **movable** major-version “stable” tags so consumers can pin to a version or follow a major line.

---

## Overview

| Concept | Meaning |
|--------|--------|
| **Component path** | Folder under the repo that represents one releasable unit (e.g. `platform/actions/dependency-check-ubi9`, `actions/my-action`). |
| **Full version tag** | Tag like `platform/actions/my-action/1.2.0`. Points to a single commit and is **never moved**. |
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
   - **component_path** (required): Path to the component folder, relative to repo root.  
     Examples: `platform/actions/dependency-check-ubi9`, `actions/my-action`.
   - **mode** (required): `promote` or `rollback`.
   - **version** (required): Target version for the **full** tag, e.g. `1.2.0` (promote) or the version you want to roll back to, e.g. `1.1.0` (rollback).
3. Run the workflow on the branch you want (usually `main` or `release/*`). For **promote**, the workflow uses the commit that is `HEAD` of that branch at run time.

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `component_path` | Yes | Folder path of the component (e.g. `actions/my-action`, `platform/actions/dependency-check-ubi9`). Defines the tag prefix. |
| `mode` | Yes | `promote` – create/move tags to current `HEAD`. `rollback` – move stable tag to an existing full-version tag. |
| `version` | Yes | Semantic version for the **full** tag (e.g. `1.2.0`). On promote this is the new version; on rollback this is the version the stable tag will point to. |

---

## Tag naming

- **Full (immutable) tag:** `{component_path}/{version}`  
  Examples: `platform/actions/my-action/1.2.0`, `actions/foo/2.0.1`.
- **Stable (movable) tag:** `{component_path}/v{major}`  
  Examples: `platform/actions/my-action/v1`, `actions/foo/v2`.

So for `component_path = platform/actions/my-action` and `version = 1.2.0`:

- Full tag: `platform/actions/my-action/1.2.0`
- Stable tag: `platform/actions/my-action/v1`

---

## Promote (mode: promote)

1. Workflow runs at **current `HEAD`** of the selected branch.
2. Creates tag **`{component_path}/{version}`** at that commit (e.g. `platform/actions/my-action/1.2.0`). This tag is **immutable** and never moved.
3. Creates or updates tag **`{component_path}/v{major}`** to point at the same commit (e.g. `platform/actions/my-action/v1`). This is the **stable** pointer.
4. Pushes both tags. The stable tag is pushed with `--force` because it is updated in place.

Use this when you are releasing a new version and want that version to become the current “stable” for that major line.

---

## Rollback (mode: rollback)

1. Does **not** create a new commit or new full-version tag.
2. Moves the **stable** tag `{component_path}/v{major}` so it points to the same commit as the **existing** full-version tag `{component_path}/{version}`.
3. Pushes the stable tag with `--force`.

**Requirement:** The full-version tag you give in `version` must already exist (from a previous promote). Example: to rollback `v1` to `1.1.0`, the tag `platform/actions/my-action/1.1.0` must already exist.

Use this when the current stable release is bad and you want consumers using `v1` (or `v2`, etc.) to get the previous good version again.

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
