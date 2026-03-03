# Rules for Writing Python Scripts and Developing Actions or Workflows

This document explains the standards we follow when writing code—whether that’s a Python script, a GitHub Action, a workflow, or automation in any language. Each rule is written so that **anyone** (including non-developers) can understand *why* it exists and *what* it means.

---

## Table of contents

1. [Document every file at the top](#1-document-every-file-at-the-top)
2. [Document every function and “block” of logic](#2-document-every-function-and-block-of-logic)
3. [Use numbered “breadcrumbs” for debugging](#3-use-numbered-breadcrumbs-for-debugging)
4. [Handle errors explicitly—never hide them](#4-handle-errors-explicitlynever-hide-them)
5. [Write small, testable, reusable pieces](#5-write-small-testable-reusable-pieces)
6. [Keep secrets out of code and docs](#6-keep-secrets-out-of-code-and-docs)
7. [Test before you call it done](#7-test-before-you-call-it-done)
8. [Leave a “checkpoint” when changing working code](#8-leave-a-checkpoint-when-changing-working-code)
9. [Use clear commit messages (and no bot names)](#9-use-clear-commit-messages-and-no-bot-names)
10. [Language-specific habits](#10-language-specific-habits)

---

## 1. Document every file at the top

**Rule:** Every new script or workflow file must start with a short “header” that describes the file in a standard way.

**Why it matters:** When someone opens the file (or when an automated tool scans it), they can immediately see what the file is for, who owns it, and how the program reports success or failure—without reading the whole file.

**What to include:**

| Field | Meaning (in plain English) |
|--------|----------------------------|
| **FILE_NAME** | The exact filename (e.g. `drift_auditor.py`). |
| **DESCRIPTION** | One or two sentences: what does this file do? (e.g. “Checks Terraform workspaces for drift and opens a GitHub issue.”) |
| **VERSION** | A version number in the form `major.minor.patch` (e.g. `1.0.0`). Lets everyone agree on “which version” they’re looking at. |
| **EXIT_CODES / SIGNALS** | What the program “returns” when it finishes: e.g. “0 = success, 1 = error, 2 = drift found.” So scripts or workflows that call it know how to react. |
| **AUTHORS** | Team or person responsible (e.g. “Platform / DevOps”). So others know who to ask. |

**Where it goes:** At the very top of the file, in a comment block (the format depends on the language—e.g. in Python we use `""" ... """`).

---

## 2. Document every function and “block” of logic

**Rule:** Every function (and every important class) must have a short description that states: what it’s for, what goes in, what comes out, and whether it touches the disk, network, or global state.

**Why it matters:** Functions are the “building blocks” of scripts and actions. If each block is clearly described, anyone (or any tool) can understand behavior without guessing. It also reduces mistakes when someone changes the code later.

**What to include:**

| Field | Meaning (in plain English) |
|--------|----------------------------|
| **INTENT** | What is this function trying to achieve? (e.g. “Fetch the list of open PRs from GitHub.”) |
| **INPUT** | What arguments does it take, and what type? (e.g. “owner and repo name (strings).”) |
| **OUTPUT** | What does it return? (e.g. “A list of PR summaries, or nothing.”) |
| **ROLE** | (For classes only.) Is this a “Service” (does work, calls APIs), “Data” (holds data), or “Model” (represents a concept)? |
| **SIDE_EFFECTS** | Does it read/write files, call the network, or change global state? (e.g. “Network: calls GitHub API.”) |

**Where it goes:** In the function’s or class’s docstring (or comment block) right at the top. We do **not** use curly braces `{}` for these keys; we use clear labels like **INTENT:**, **INPUT:**, etc.

---

## 3. Use numbered “breadcrumbs” for debugging

**Rule:** At important steps in the code (e.g. “started”, “calling API”, “writing result”), we add a *numbered trace* so that when something goes wrong, we can see exactly where the run reached. Error paths get their own numbers with an “ERR” prefix. By default, these traces are **commented out** so they don’t clutter normal runs; they can be turned on when debugging.

**Why it matters:** In automation (scripts, actions, workflows), failures often happen in CI or in production. Numbered traces (e.g. `[T-01]`, `[T-02]`, `[ERR-T-01]`) make logs easy to search and let support or developers say “the run failed at step T-03” or “error branch ERR-T-02.”

**Conventions:**

- Normal steps: `[T-01]`, `[T-02]`, …
- Error branches: `[ERR-T-01]`, `[ERR-T-02]`, …
- In code they are usually written as comments, e.g.  
  `# _log("[T-01] Starting process")`  
  so they don’t run unless someone uncomments them.

---

## 4. Handle errors explicitly—never hide them

**Rule:** Every place we do something that can fail (read a file, call an API, run a command) must use a “try–catch” or “check–error” pattern. We must not ignore errors or return without reporting them. Each error path should be tied to a trace number (see above) so we can debug later.

**Why it matters:** If we hide or ignore errors, a script or workflow can “succeed” while something actually failed (e.g. a step didn’t run, or data wasn’t written). That leads to wrong decisions and hard-to-find bugs. Explicit handling means failures are visible and traceable.

**In practice:** Use the normal pattern for the language (e.g. in Python: `try` / `except`; in Shell: check exit codes and `exit 1` on failure). In the “catch” or error block, log or re-raise with context, and reference the trace number (e.g. `[ERR-T-01]`).

---

## 5. Write small, testable, reusable pieces

**Rule:** Prefer small, focused scripts or workflow steps. Use variables and configuration (env vars, config files, secrets managers) instead of hardcoding. Write so that the same steps can be run repeatedly without surprise (idempotency where it makes sense). Name things consistently (e.g. kebab-case for resources, snake_case for variables in scripts).

**Why it matters:** Small, well-named pieces are easier to understand, test, and reuse across different workflows or repos. Hardcoded values and one-off scripts are hard to maintain and to explain to non-technical stakeholders.

**In practice:**

- Break big workflows into smaller jobs or steps.
- Use English for names and comments.
- Avoid hardcoding secrets, URLs, or environment-specific values; use configuration or secrets managers instead.

---

## 6. Keep secrets out of code and docs

**Rule:** Passwords, API tokens, and other secrets must never be written directly in code or in documentation. They should live in a secrets manager (e.g. GitHub Secrets, AWS Secrets Manager, External Secrets) and be passed in at run time (e.g. via environment variables or workflow inputs).

**Why it matters:** Code and docs are often shared, versioned, or visible in logs. Putting secrets there risks exposure. Keeping them in a dedicated store and injecting them when the script or workflow runs is the safe, standard approach.

---

## 7. Test before you call it done

**Rule:** Before considering a script, action, or workflow “complete,” we run the relevant tests (e.g. unit tests, lint, or a dry run). For UI or app changes, we run the project’s validation (e.g. `yarn validate:ui`) and fix any failures. Documentation is updated **after** the change is verified to work.

**Why it matters:** Shipping untested code leads to broken automation and confused users. Running tests and validation gives confidence that the change does what we intend. Updating docs only after success keeps the docs aligned with reality.

---

## 8. Leave a “checkpoint” when changing working code

**Rule:** When we change code that *already works* (e.g. a fix, refactor, or behavior change), we add a short comment just above the change that describes what the *previous* behavior was. We use a consistent tag such as `CHECKPOINT:` or `ANCHOR:` so it’s easy to search. We don’t add these for brand-new code or trivial typos.

**Why it matters:** If the new change causes a problem, anyone (including non-developers) can search for “CHECKPOINT” or “ANCHOR” to see what the code did before and decide whether to revert or adjust.

**In practice:** One to three lines describing “what it did before,” e.g.  
`# CHECKPOINT: Previously we only showed rows with total_seconds > 0.`

---

## 9. Use clear commit messages (and no bot names)

**Rule:** When pushing code to GitHub (or any version control), write clear, conventional commit messages (e.g. `feat: add drift exclude patterns`, `fix: correct exit code when init fails`). Do **not** include tool or bot names (e.g. “cursor-bot”, “Cursor Bot”) in the commit message subject or body.

**Why it matters:** Good commit messages help everyone understand what changed and why, and make it easier to search history. Keeping bot/tool names out of messages keeps the history professional and focused on the change itself.

---

## 10. Language-specific habits

These are short, practical habits we follow per language or tool. They keep our scripts, actions, and workflows consistent and maintainable.

### Python

- Use a recent stable Python (e.g. 3.12+).
- Include `from __future__ import annotations` at the top of files that use type hints.
- Use a single style/format (e.g. Black) and type-check (e.g. mypy).
- Prefer structured logging (e.g. DEBUG/INFO/ERROR) and custom exceptions with context.
- Scripts that run as “main” should use `if __name__ == "__main__":` and read config from environment or settings (e.g. pydantic-settings, python-dotenv).
- Write tests (e.g. pytest) and run them before marking work complete.

### Shell (Bash/Zsh)

- Use `set -euo pipefail` so the script stops on errors and undefined variables.
- Use functions for repeated logic and `trap` for cleanup on exit/error.
- Quote variables and handle errors explicitly (e.g. `|| { echo "ERROR"; exit 1; }`).
- For commands that are allowed to fail (e.g. cleanup), use `|| true` so they don’t fail the whole script.

### GitHub Actions and workflows

- Put workflows under `.github/workflows/` and prefer **official actions** (`actions/*`) where possible.
- Use OIDC or short-lived credentials; avoid long-lived secrets in code.
- **YAML anchors:** Use anchors only for **non-security** repeated blocks (e.g. shared checkout step, repeated **env** maps). **Do not use anchors for `permissions`:** GitHub’s parser can treat permission blocks with strict schema validation, and OWASP SPVS prefers **explicit per-job permissions** so auditors see the exact scope without tracing YAML references. Define permissions explicitly on each job; for reuse across repos, use **reusable workflows**, not anchors.
- Workflows that can be triggered automatically (e.g. on push/PR) should also support manual run (`workflow_dispatch`) with the same inputs when that makes sense.
- Before building a new action, write down pros/cons versus using a few plain steps, and decide who will call it and how it should fail.

### Terraform / infrastructure as code

- Describe variables and outputs clearly; use validation where possible.
- Keep secrets out of state and variables; use a secrets manager or external data.
- Use remote state with locking and encryption; run `terraform plan` (or equivalent) in CI.
- Generate module docs (e.g. with terraform-docs) instead of hand-writing input/output tables.

### Docker / containers

- Use multi-stage builds and a non-root user where possible.
- Add standard labels (e.g. source, version, maintainer).
- Run a security scan (e.g. Trivy) in the build pipeline and fail the build on critical issues.

### Kubernetes / OpenShift

- Use namespaces, RBAC, and network policies to isolate workloads.
- Prefer Helm/Kustomize and generate chart README (e.g. helm-docs); add unit tests for main scenarios.
- Validate manifests (e.g. `kubectl apply --dry-run=client`) before applying.

---

## Summary

| # | Rule | One-line summary |
|---|------|------------------|
| 1 | Document every file | Put FILE_NAME, DESCRIPTION, VERSION, EXIT_CODES, AUTHORS at the top. |
| 2 | Document every function | Add INTENT, INPUT, OUTPUT, and SIDE_EFFECTS (and ROLE for classes). |
| 3 | Numbered breadcrumbs | Use [T-xx] and [ERR-T-xx] in comments for debugging; keep them commented by default. |
| 4 | Handle errors | Use try/catch or check/error; never hide or ignore failures. |
| 5 | Small, reusable pieces | Prefer small steps, config over hardcoding, consistent naming. |
| 6 | No secrets in code | Use a secrets manager; never commit secrets. |
| 7 | Test before done | Run tests and validation; update docs after success. |
| 8 | Checkpoints | When changing working code, add a CHECKPOINT/ANCHOR comment above. |
| 9 | Clear commits | Use conventional messages; do not include bot/tool names. |
| 10 | Language habits | Follow the Python, Shell, Actions, Terraform, Docker, and K8s habits above. |

These rules apply to **any** programming language or workflow system we use (Python, Go, Shell, GitHub Actions, Terraform, Tekton, etc.). The goal is clarity, safety, and maintainability so that both technical and non-technical stakeholders can understand and rely on our automation.
