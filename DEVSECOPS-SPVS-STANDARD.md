# DevSecOps Technical Standard (OWASP SPVS v1.0 Aligned)

This document is the **technical standard** for Python- and Shell-based GitHub Actions in this repository. It synthesizes **OWASP Secure Pipeline Verification Standard (SPVS) v1.0** into actionable checklists and implementation guidance. Use it for code review, onboarding, and CI enforcement.

**References:** [OWASP SPVS](https://owasp.org/www-project-spvs) · [GitHub SPVS](https://github.com/OWASP/www-project-spvs) · [SPVS Release 1.0](https://github.com/OWASP/www-project-spvs/tree/Release-1.0/1.0)

---

## Table of contents

1. [GitHub Actions & Workflow Hardening](#part-1-github-actions--workflow-hardening) (SPVS V1 Plan, V3 Integrate)
2. [Python Scripting Standards](#part-2-python-scripting-standards) (SPVS V2 Develop)
3. [Shell Scripting (Bash/Sh) Standards](#part-3-shell-scripting-bashsh-standards) (SPVS V2 Develop)
4. [Automated Verification Checklist](#part-4-automated-verification-checklist)
5. [Summary checklist](#summary-checklist)

---

## Part 1: GitHub Actions & Workflow Hardening

*SPVS categories: **V1 (Plan)** and **V3 (Integrate)***

### 1.1 Identity & Access Management (V1.1)

#### Least-privilege `GITHUB_TOKEN`

- [ ] **Set default permissions at the top of every workflow.** Use `permissions: contents: read` as the workflow default. Only grant elevated permissions to jobs that need them.
- [ ] **Scope permissions per job.** Add `contents: write`, `id-token: write`, `attestations: write`, etc. only on the specific job that performs the action (e.g. a job that pushes tags or uploads artifacts).
- [ ] **Never use workflow-level `write-all` or broad write.** Prefer explicit scopes (e.g. `contents: write`) over `permissions: write-all`.
- [ ] **Do not use YAML anchors for `permissions`.** Declare permissions explicitly per job so GitHub’s schema validation and SPVS auditability see exact scope. For reuse across repos, use reusable workflows, not anchors.

**Example (workflow default):**

```yaml
permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  release:
    needs: build
    permissions:
      contents: write   # Only this job can push
    runs-on: ubuntu-latest
    steps:
      - run: git push origin main
```

**Rationale:** Reduces blast radius if a step or action is compromised; aligns with SPVS V1.1 (identity and access).

---

#### OpenID Connect (OIDC)

- [ ] **Use OIDC for cloud deployments.** For AWS, Azure, or GCP, request an OIDC token from the GitHub Actions runner and exchange it for short-lived cloud credentials. Do not store long-lived static access keys in GitHub Secrets.
- [ ] **Document OIDC usage.** Where OIDC is used, document the trust relationship (e.g. which repo/branch/environment can assume which IAM role).

**Rationale:** Eliminates long-lived secrets; SPVS encourages short-lived, scoped credentials.

---

#### Environment protection

- [ ] **Use GitHub Environments for production.** For any workflow that deploys to production (or a production-like environment), use an Environment (e.g. `production`) with required reviewers and (optionally) wait timer.
- [ ] **Restrict which branches can use the environment.** In Environment settings, limit deployment to `main` or protected release branches.

**Example:**

```yaml
jobs:
  deploy:
    environment: production
    runs-on: ubuntu-latest
```

**Rationale:** SPVS V1 and V4 (Release) stress controlled, auditable releases.

---

#### Same-repo push (GitHub App installation token required)

- [ ] **For workflows that push to the same repo (e.g. release, promote, rollback), use a GitHub App installation token.** Do not use a personal access token (PAT). Create a GitHub App with repository permission **Contents: Read and write**, install it on the repo, and supply the installation token as the workflow secret (e.g. `COMMIT_TOKEN`). Installation tokens are short-lived, scoped to the App (no personal user account), and support fine-grained permissions.
- [ ] **Reserve PATs for temporary use only.** If a PAT is used in exception, it must be a fine-grained PAT with minimal scope. Rotate regularly and replace with a GitHub App as soon as possible.

**Rationale:** Eliminates long-lived secrets and personal-account dependency; aligns with SPVS identity and least-privilege.

---

### 1.2 Supply chain integrity (V3.4)

#### SHA pinning for third-party actions

- [ ] **Prefer 40-character commit SHA for third-party actions.** Use the full SHA of the commit you have reviewed (e.g. `uses: actions/checkout@11bd7190...`) instead of a tag (e.g. `@v4`) when your security policy requires it.
- [ ] **Document exceptions.** If you use tags (e.g. `@v4`) for convenience, document that in this standard or in the workflow comment, and ensure Dependabot or equivalent can update actions.

**Example (SHA-pinned):**

```yaml
- uses: actions/checkout@11bd7190b36b6a2b8e2d2e8b8e2e2e2e2e2e2e2e2e
```

**Rationale:** Prevents tag hijacking and ensures a fixed, reviewed commit; SPVS V3.4 (supply chain integrity).

---

#### Internal reusable workflows

- [ ] **Reference internal workflows with SemVer.** When calling your own reusable workflows, use tags that follow Semantic Versioning (e.g. `workflows/release@1.2.0` or `@v1`).
- [ ] **Enable tag protection.** Use repository rulesets or tag protection so that release tags cannot be force-moved or deleted by unauthorized users.
- [ ] **Avoid `@main` or `@HEAD` for production paths.** Prefer a released tag so that changes to `main` do not automatically affect production.

**Rationale:** Prevents accidental or malicious tag manipulation; aligns with SPVS supply chain controls.

---

#### Artifact attestation

- [ ] **Every build/release job must produce attestations.** Include `actions/attest-build-provenance` (or `actions/attest`) in jobs that produce release artifacts (containers, binaries, or release commits). Attest the artifact path and use a stable subject name (e.g. `release:path@version`).
- [ ] **Grant attestation permissions.** The job must have `id-token: write` and `attestations: write`.

**Example:**

```yaml
- uses: actions/attest-build-provenance@v2
  with:
    subject-path: .
    subject-name: "release:${{ env.COMPONENT }}@${{ env.VERSION }}"
```

**Rationale:** SPVS V3/V4 stress artifact integrity and provenance; attestations provide a signed record of build origin.

---

## Part 2: Python Scripting Standards

*SPVS category: **V2 (Develop)***

### 2.1 Secure coding (V2.1)

#### No shell injection

- [ ] **Never use `shell=True` in subprocess.** Always pass a list of arguments: `subprocess.run(["cmd", "arg1", path], shell=False)`. This prevents shell metacharacter injection.
- [ ] **Never pass user or event input to `os.system()`, `eval()`, or `exec()`.** Use Python APIs (e.g. `pathlib`, `shutil`, `json`) or list-based subprocess instead.
- [ ] **If you must build a shell string** (e.g. for a legacy tool), use `shlex.quote()` on every user-controlled segment and prefer list-based subprocess when possible.

**Example (safe):**

```python
import subprocess

path = user_input  # Assume validated
subprocess.run(["ls", "-l", path], check=True, capture_output=True)
```

**Example (unsafe – do not use):**

```python
os.system(f"ls -l {path}")           # Injection risk
subprocess.run(f"ls -l {path}", shell=True)  # Injection risk
eval(user_input)                    # Arbitrary code execution
```

**Rationale:** SPVS V2.1 (secure coding); prevents command injection and arbitrary code execution.

---

#### Safe path handling (directory traversal prevention)

- [ ] **Use `pathlib.Path` for file operations.** Prefer `Path` methods over string concatenation.
- [ ] **Validate paths stay within expected roots.** Before reading or writing, resolve the path and check that it is under the allowed base directory (e.g. workspace or a known safe root). Use `.resolve()` and compare with a trusted base.
- [ ] **Reject path segments containing `..`** when accepting user or event input as path components.

**Example:**

```python
from pathlib import Path

def safe_read(base: Path, relative: str) -> Path:
    base = base.resolve()
    candidate = (base / relative).resolve()
    if not str(candidate).startswith(str(base)):
        raise ValueError("Path escapes base directory")
    return candidate
```

**Rationale:** Prevents directory traversal (e.g. `../../etc/passwd`); SPVS V2.1.

---

#### Input validation (GitHub event payloads)

- [ ] **Validate data from GitHub event payloads.** Event payloads (e.g. `github.event.inputs`, `github.event.repository`) are untrusted from a security perspective. Validate types, lengths, and allowlists before use.
- [ ] **Use type hints and Pydantic (or similar).** Define schemas for inputs (e.g. workflow_dispatch inputs) and validate with Pydantic `BaseModel` so that invalid or unexpected shapes are rejected early.
- [ ] **Allowlist allowed values.** For fields like `component_path` or `mode`, validate against a fixed set or regex (e.g. `^(actions|workflows)/[a-zA-Z0-9_.-]+$`) instead of blacklisting.

**Example (Pydantic):**

```python
from pydantic import BaseModel, Field

class WorkflowInputs(BaseModel):
    component_path: str = Field(..., pattern=r"^(actions|workflows)/[a-zA-Z0-9_.-]+$")
    version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    mode: str = Field(..., pattern=r"^(rc|promote|rollback)$")
```

**Rationale:** SPVS V2.1; prevents injection and logic errors from malformed or malicious event data.

---

### 2.2 Dependency management (V2.6)

- [ ] **Enable vulnerability scanning.** Use GitHub Dependabot (or equivalent) to scan `requirements.txt`, `pyproject.toml`, or `Pipfile.lock` for known vulnerabilities.
- [ ] **Pin dependencies.** Use exact versions (e.g. `package==1.2.3`). Where supported, use hashes (e.g. pip hash mode or lockfiles with hashes) for reproducible and tamper-resistant installs.
- [ ] **Review and update dependencies regularly.** Treat Dependabot alerts as high priority; address critical/high vulnerabilities before release.

**Example (`requirements.txt`):**

```
# Pinned; update via Dependabot or controlled PRs
requests==2.31.0
pydantic>=2.0,<3
```

**Rationale:** SPVS V2.6 (dependency management); reduces risk from vulnerable or compromised packages.

---

## Part 3: Shell Scripting (Bash/Sh) Standards

*SPVS category: **V2 (Develop)***

### 3.1 Script hardening

#### The “safe header”

- [ ] **Every script must start with `set -euo pipefail`** (or equivalent in non-Bash shells where supported).
  - **`-e`:** Exit immediately if a command exits with non-zero status.
  - **`-u`:** Treat unset variables as an error and exit.
  - **`-o pipefail`:** In a pipeline, the return value is the status of the rightmost command that exited non-zero (so a failure in an early stage is not ignored).
- [ ] **Do not disable these in the middle of the script** unless there is a documented, narrow exception (e.g. a command that is allowed to fail with `|| true`).

**Example:**

```bash
#!/usr/bin/env bash
set -euo pipefail

# rest of script
```

**Rationale:** Catches errors and use of uninitialized variables; SPVS V2 (Develop).

---

#### Double-quoting variables

- [ ] **Always double-quote variable expansions:** use `"$VAR"` instead of `$VAR`. This prevents word splitting and glob expansion that can lead to injection or unintended multiple arguments.
- [ ] **Quote command substitutions** when assigning or using: `dir="$(pwd)"` and then `cd "$dir"`.

**Example (safe):**

```bash
path="$INPUT_PATH"
cp "$path" /dest/
```

**Example (unsafe):**

```bash
cp $path /dest/   # Word splitting if path contains spaces
```

**Rationale:** Prevents word-splitting and globbing attacks; SPVS V2.

---

#### No direct context interpolation in GitHub Actions `run` blocks

- [ ] **Never use `${{ github.event... }}` (or other GitHub context) directly inside a shell `run:` script.** The context is injected at workflow parse time and can be misused if the script passes it to external commands; it also makes auditing harder.
- [ ] **Map context to job or step `env` variables.** Define e.g. `env: PATH_NAME: ${{ github.event.inputs.component_path }}` and use `"$PATH_NAME"` in the script. This keeps a single place where context is bound and makes the script testable with explicit env vars.

**Example (preferred):**

```yaml
env:
  PATH_NAME: ${{ github.event.inputs.component_path }}
  VER: ${{ github.event.inputs.version }}
steps:
  - run: |
      set -euo pipefail
      [[ -d "$PATH_NAME" ]] || { echo "::error::Path $PATH_NAME not found"; exit 1; }
      echo "Version: $VER"
```

**Example (avoid):**

```yaml
- run: |
    path="${{ github.event.inputs.component_path }}"
    [[ -d "$path" ]] || exit 1
```

**Rationale:** Clear separation of workflow context and script; reduces injection and improves auditability; aligns with SPVS and internal DevSecOps rules.

---

### 3.2 Validation and privilege

- [ ] **Lint all `.sh` files in CI.** Run ShellCheck (e.g. `shellcheck --external-sources`) on every shell script in the repository. Fail the job if ShellCheck reports errors (and optionally warnings, per policy).
- [ ] **Avoid `sudo` inside scripts** unless required for runner or system configuration (e.g. installing a package). Prefer running the entire job with appropriate permissions or using a dedicated “setup” step with sudo rather than sprinkling sudo in business logic.

**Rationale:** SPVS V2 (Develop); automated checks enforce consistent hardening; least privilege.

---

## Part 4: Automated Verification Checklist

Use these **native or minimal-tool** checkpoints to satisfy SPVS controls without introducing unnecessary third-party services. These can be enforced via repository settings, GitHub Actions, or a dedicated Security-Gate workflow.

| SPVS control | Description | Native implementation |
| --- | --- | --- |
| **V1.5 SCM hardening** | Source control and commit integrity | **Repository rulesets:** Require signed commits, linear history, and (optionally) status checks before merge. Branch protection for default and release branches. |
| **V2.4 Security checks** | Early detection of secrets and vulnerabilities | **GitHub Secret Scanning** with Push Protection enabled. **Code scanning** (CodeQL or third-party) on push/PR. |
| **V3.3 Continuous scanning** | Dependencies and supply chain | **Dependency Graph** and **Dependabot alerts** enabled. **Dependabot security updates** or scheduled dependency updates. |
| **V4.1 Release integrity** | Controlled, auditable releases | **Protected Environments** with required reviewers for production. Optional deployment branches and wait timers. |
| **V2/V3 Pipeline checks** | Script and workflow security | **ShellCheck** on all `.sh` files in CI. **Checkov** (or similar) with `framework: github_actions` on workflow YAML. **Permission audit:** workflow/job `permissions:` default to `contents: read`. |

---

## Summary checklist

Quick reference for PR and release gates:

**GitHub Actions**

- [ ] Default `permissions: contents: read`; scope write to specific jobs.
- [ ] Avoid anchors for permissions; keep permissions explicit per job for auditability.
- [ ] OIDC for cloud; Environments for production with reviewers.
- [ ] SHA-pin third-party actions where required; SemVer + tag protection for internal workflows.
- [ ] Attest build/release artifacts; `id-token: write` and `attestations: write` where needed.

**Python**

- [ ] No `shell=True`; no `eval`/`exec`/`os.system()`; list-based subprocess; `shlex.quote()` only when necessary.
- [ ] Path validation with `pathlib` and `.resolve()`; reject path traversal.
- [ ] Pydantic/type-hint validation for event payloads; allowlist inputs.
- [ ] Dependabot enabled; pinned (and hashed where possible) dependencies.

**Shell**

- [ ] `set -euo pipefail` at the top of every script.
- [ ] Double-quote all variables: `"$VAR"`.
- [ ] No `${{ }}` inside `run:`; use `env:` and script variables only.
- [ ] ShellCheck on all `.sh` in CI; avoid unnecessary `sudo`.

**Automated verification**

- [ ] Signed commits / linear history (rulesets); Secret Scanning + Push Protection.
- [ ] Dependency Graph + Dependabot; Protected Environments for production.
- [ ] ShellCheck + Checkov (github_actions) in pipeline; permission audit.

**Operational – documentation sync**

- [ ] Every new Action or Workflow has a corresponding `.md` file in its folder (e.g. `readme.md` or `README.md`) that describes the component and aligns with this technical standard.
- [ ] Each action/workflow folder is checked for the presence of that readme (e.g. in CI or at promotion time); missing readme blocks release or is reported.

---

## Related documentation

- [OWASP SPVS alignment](owasp-spvs.md) – How this repo uses SPVS at a high level.
- [Platform Component Manager](readme-platform-component-manager.md) – Release workflow and Stage 2 (Security SPVS) full-repo validation.
- [Security and tokens](readme-platform-component-manager.md#security-and-tokens) – Token and GitHub App guidance for protected branches.

---

*This standard is aligned with OWASP SPVS v1.0 and is intended for use in code review, CI gates, and security training. Update when SPVS or internal policy changes.*
