# ------------------------------------------------------------------------------
# Repository (existing or to be created)
# ------------------------------------------------------------------------------

variable "repository" {
  description = "Repository in the form 'owner/name' (e.g. my-org/my-repo). When create_repository is true, only the 'name' part is used; provider owner must match the 'owner' part."
  type        = string
}

variable "create_repository" {
  description = "When true, create the GitHub repository; when false, use an existing repo (data source)."
  type        = bool
  default     = false
}

variable "description" {
  description = "Short description of the repository (used when create_repository is true)."
  type        = string
  default     = ""
}

variable "visibility" {
  description = "Repository visibility: 'public', 'private', or 'internal' (GitHub Enterprise)."
  type        = string
  default     = "private"
}

variable "auto_init" {
  description = "When true, create the repo with an initial commit and default branch (recommended true so main exists for protection)."
  type        = bool
  default     = true
}

variable "default_branch" {
  description = "Default branch name (e.g. main). Used when create_repository is true; ensure it exists (auto_init creates it)."
  type        = string
  default     = "main"
}

variable "delete_branch_on_merge" {
  description = "Automatically delete head branches after merge (industry standard for clean branch list)."
  type        = bool
  default     = true
}

variable "allow_squash_merge" {
  description = "Allow squash merging (recommended for linear history)."
  type        = bool
  default     = true
}

variable "allow_merge_commit" {
  description = "Allow merge commits (typically false when requiring linear history)."
  type        = bool
  default     = false
}

variable "allow_rebase_merge" {
  description = "Allow rebase merging."
  type        = bool
  default     = true
}

variable "has_issues" {
  description = "Enable issues."
  type        = bool
  default     = true
}

variable "has_wiki" {
  description = "Enable wiki (often disabled for code-only repos)."
  type        = bool
  default     = false
}

variable "has_projects" {
  description = "Enable projects (classic)."
  type        = bool
  default     = false
}

variable "has_discussions" {
  description = "Enable discussions."
  type        = bool
  default     = false
}

variable "vulnerability_alerts" {
  description = "Enable security alerts for vulnerable dependencies (Dependabot)."
  type        = bool
  default     = true
}

variable "allow_forking" {
  description = "Allow forking (for private repos, often false)."
  type        = bool
  default     = false
}

variable "archive_on_destroy" {
  description = "When true, archive the repo on destroy instead of deleting (safer)."
  type        = bool
  default     = false
}

variable "topics" {
  description = "List of topics (labels) for the repository."
  type        = list(string)
  default     = []
}

# ------------------------------------------------------------------------------
# Branch patterns (default: main and develop)
# ------------------------------------------------------------------------------

variable "protected_branches" {
  description = "List of branch names or patterns to protect (e.g. ['main', 'develop']). Release branches can be added via protect_release_branch."
  type        = list(string)
  default     = ["main", "develop"]
}

variable "protect_release_branch" {
  description = "When true, add release_branch_pattern to protected branches (industry standard: protect release/*)."
  type        = bool
  default     = true
}

variable "release_branch_pattern" {
  description = "Branch pattern for release branches (e.g. release/*). Used when protect_release_branch is true."
  type        = string
  default     = "release/*"
}

# ------------------------------------------------------------------------------
# Pull request requirements (industry standard: require PR + reviews)
# ------------------------------------------------------------------------------

variable "required_approving_review_count" {
  description = "Number of approving reviews required before merging."
  type        = number
  default     = 1
}

variable "dismiss_stale_reviews" {
  description = "Dismiss approved reviews when new commits are pushed."
  type        = bool
  default     = true
}

variable "require_code_owner_reviews" {
  description = "Require review from code owners when relevant."
  type        = bool
  default     = false
}

variable "require_conversation_resolution" {
  description = "Require all conversation threads to be resolved before merging."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Status checks (optional: pass list of context names from your CI)
# ------------------------------------------------------------------------------

variable "required_status_checks" {
  description = "Map of branch pattern to list of status check context names (e.g. {'main' = ['ci'], 'develop' = ['ci']}). Omit or use empty list to not require status checks."
  type        = map(list(string))
  default     = {}
}

variable "require_branches_up_to_date" {
  description = "Require branches to be up to date before merging (only applies when required_status_checks is set)."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Safety and history
# ------------------------------------------------------------------------------

variable "allow_force_pushes" {
  description = "Allow force pushes to protected branches. Should be false for main/develop in most cases."
  type        = bool
  default     = false
}

variable "allow_deletions" {
  description = "Allow deletion of protected branches. Should be false for main/develop."
  type        = bool
  default     = false
}

variable "require_linear_history" {
  description = "Require linear history (no merge commits; use squash/rebase)."
  type        = bool
  default     = true
}

variable "require_signed_commits" {
  description = "Require commits to be signed. Enable if your org uses verified commits."
  type        = bool
  default     = false
}

# ------------------------------------------------------------------------------
# Admin enforcement
# ------------------------------------------------------------------------------

variable "enforce_admins" {
  description = "Enforce these rules for repository administrators (recommended true for main/develop)."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Lock branch (optional, use sparingly)
# ------------------------------------------------------------------------------

variable "lock_branch" {
  description = "When true, prevents creating new changes, merging PRs, or pushing (use for archived release branches only)."
  type        = bool
  default     = false
}
