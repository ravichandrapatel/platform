# GitHub Repository & Branch Protection Module

Terraform module that **creates** a GitHub repository (optional) and applies **industry-standard branch protection rules** for **main** and **develop** (or any branch patterns you specify). Uses the [integrations/github](https://registry.terraform.io/providers/integrations/github/latest) provider **~> 6.11**. No teams or user assignments—repo and protection only.

## Pull request rules

Branch protection **is** the pull request policy: all changes to protected branches must go through a PR. The module enforces:

- **Require pull request** – no direct pushes to main, develop, or release branches
- **Required approving review count** – at least one approval (configurable)
- **Dismiss stale reviews** – new commits invalidate prior approvals
- **Require conversation resolution** – all PR threads must be resolved before merge
- **Optional status checks** – require CI (e.g. `ci`, `lint`) via `required_status_checks`

Repo-level merge options are set on the repository: squash and rebase allowed, merge commits disabled by default (linear history).

## Release branch rules

By default the module also protects **release branches** so they follow the same PR and safety rules as main/develop:

- **Pattern:** `release/*` (e.g. `release/1.0`, `release/2.0`) is added to protected branches when `protect_release_branch = true` (default).
- **Same rules:** Require PR, reviews, no force push, no deletion, linear history. Use `required_status_checks` with key `release/*` to require CI on release branches.
- **Disable:** Set `protect_release_branch = false` to protect only `protected_branches` (main, develop). Override the pattern with `release_branch_pattern` (e.g. `release` for a single branch).

## What it enforces (defaults)

| Setting | main / develop / release/* | Rationale |
|--------|-----------------------------|-----------|
| Require pull request | Yes | No direct pushes; all changes via PR |
| Required approving reviews | 1 | At least one reviewer before merge |
| Dismiss stale reviews | Yes | New commits require re-review |
| Require conversation resolution | Yes | All PR comments resolved before merge |
| Require linear history | Yes | Squash or rebase only; no merge commits |
| Allow force pushes | No | Prevents rewriting history |
| Allow branch deletion | No | Prevents accidental deletion |
| Enforce for admins | Yes | Same rules for everyone |
| Require signed commits | No | Enable via variable if your org uses them |
| Require status checks | Optional | Pass `required_status_checks` to require CI |

## Usage

### Create repository and protect main + develop (recommended for new repos)

```hcl
provider "github" {
  owner = "my-org"  # must match owner in repository
  # token from GITHUB_TOKEN or token = var.github_token
}

module "repo" {
  source = "../../modules/github-branch-protection"

  repository        = "my-org/my-repo"
  create_repository = true
  description       = "My application repository"
  visibility        = "private"
  # develop branch is created from main and protected automatically
}
```

### Existing repository (protect branches only)

```hcl
module "repo_branch_protection" {
  source = "../../modules/github-branch-protection"

  repository = "my-org/my-repo"
  # create_repository = false (default)
}
```

### With status checks (main, develop, release/*)

```hcl
module "repo_branch_protection" {
  source = "../../modules/github-branch-protection"

  repository = "my-org/my-repo"

  required_status_checks = {
    main        = ["ci", "lint"]
    develop     = ["ci", "lint"]
    "release/*" = ["ci", "lint"]
  }
  require_branches_up_to_date = true
  # protect_release_branch = true (default) protects release/*
}
```

### Custom branches and stricter reviews

```hcl
module "repo_branch_protection" {
  source = "../../modules/github-branch-protection"

  repository          = "my-org/my-repo"
  protected_branches  = ["main", "develop", "release"]

  required_approving_review_count = 2
  require_code_owner_reviews      = true
  require_signed_commits          = true
}
```

### With provider (root or env)

```hcl
terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.11"
    }
  }
}

provider "github" {
  owner = "my-org"
  # token from GITHUB_TOKEN env or token = var.github_token
}

module "repo_branch_protection" {
  source = "../../modules/github-branch-protection"
  repository = "my-org/my-repo"
}
```

## Repository defaults (when create_repository = true)

| Setting | Default | Rationale |
|---------|---------|-----------|
| visibility | `private` | Secure by default |
| default_branch | `main` | Common standard |
| auto_init | `true` | Ensures default branch exists for protection |
| delete_branch_on_merge | `true` | Clean branch list |
| allow_squash_merge | `true` | Linear history |
| allow_merge_commit | `false` | No merge commits |
| allow_rebase_merge | `true` | Linear history |
| has_issues | `true` | Tracking |
| has_wiki / has_projects | `false` | Code-focused |
| vulnerability_alerts | `true` | Dependabot security |
| allow_forking | `false` | Private repos |
| archive_on_destroy | `false` | Set true to archive instead of delete |

When `create_repository` is true and `protected_branches` includes `develop`, the module creates the `develop` branch from the default branch so it can be protected.

## Inputs

| Name | Type | Default | Description |
|------|------|---------|-------------|
| **Repository** | | | |
| `repository` | `string` | (required) | Repository as `owner/name`; when creating, provider `owner` must match |
| `create_repository` | `bool` | `false` | If true, create the repo; if false, use existing (data source) |
| `description` | `string` | `""` | Short description (create only) |
| `visibility` | `string` | `"private"` | `public`, `private`, or `internal` |
| `auto_init` | `bool` | `true` | Create initial commit and default branch |
| `default_branch` | `string` | `"main"` | Default branch name |
| `delete_branch_on_merge` | `bool` | `true` | Delete head branch after merge |
| `allow_squash_merge` | `bool` | `true` | Allow squash merge |
| `allow_merge_commit` | `bool` | `false` | Allow merge commits |
| `allow_rebase_merge` | `bool` | `true` | Allow rebase merge |
| `has_issues` | `bool` | `true` | Enable issues |
| `has_wiki` | `bool` | `false` | Enable wiki |
| `has_projects` | `bool` | `false` | Enable projects |
| `has_discussions` | `bool` | `false` | Enable discussions |
| `vulnerability_alerts` | `bool` | `true` | Dependabot alerts |
| `allow_forking` | `bool` | `false` | Allow forking |
| `archive_on_destroy` | `bool` | `false` | Archive on destroy |
| `topics` | `list(string)` | `[]` | Repository topics |
| **Branch protection** | | | |
| `protected_branches` | `list(string)` | `["main", "develop"]` | Branch names or patterns to protect |
| `protect_release_branch` | `bool` | `true` | Add release_branch_pattern to protected branches |
| `release_branch_pattern` | `string` | `"release/*"` | Pattern for release branches (e.g. release/*) |
| `required_approving_review_count` | `number` | `1` | Approvals required before merge |
| `dismiss_stale_reviews` | `bool` | `true` | Dismiss approvals on new commits |
| `require_code_owner_reviews` | `bool` | `false` | Require code owner review when applicable |
| `require_conversation_resolution` | `bool` | `true` | All threads resolved before merge |
| `required_status_checks` | `map(list(string))` | `{}` | Branch → list of status check contexts |
| `require_branches_up_to_date` | `bool` | `true` | Branch must be up to date when status checks are used |
| `allow_force_pushes` | `bool` | `false` | Allow force pushes |
| `allow_deletions` | `bool` | `false` | Allow branch deletion |
| `require_linear_history` | `bool` | `true` | Require linear history (squash/rebase) |
| `require_signed_commits` | `bool` | `false` | Require signed commits |
| `enforce_admins` | `bool` | `true` | Enforce rules for admins |
| `lock_branch` | `bool` | `false` | Lock branch (e.g. archived release) |

## Outputs

| Name | Description |
|------|-------------|
| `repository_id` | Repository node ID |
| `repository_name` | Full name (owner/name) |
| `repository_html_url` | URL to the repo on GitHub |
| `protected_branch_patterns` | List of protected branch patterns |
| `branch_protection_ids` | Map of pattern → protection rule ID |

## Authentication

Set `GITHUB_TOKEN` (or use `token` in the provider block) with a PAT or GitHub App token that has **admin** (or at least **push**) permission on the repository so it can manage branch protection rules.
