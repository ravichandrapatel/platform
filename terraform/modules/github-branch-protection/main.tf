# =============================================================================
# Repository (create or reference existing)
# =============================================================================

resource "github_repository" "this" {
  count = var.create_repository ? 1 : 0

  name        = split("/", var.repository)[1]
  description = var.description
  visibility  = var.visibility

  default_branch = var.default_branch
  auto_init      = var.auto_init

  delete_branch_on_merge = var.delete_branch_on_merge
  allow_squash_merge     = var.allow_squash_merge
  allow_merge_commit     = var.allow_merge_commit
  allow_rebase_merge     = var.allow_rebase_merge

  has_issues       = var.has_issues
  has_wiki         = var.has_wiki
  has_projects     = var.has_projects
  has_discussions  = var.has_discussions

  vulnerability_alerts = var.vulnerability_alerts
  allow_forking        = var.allow_forking
  archive_on_destroy   = var.archive_on_destroy
  topics               = var.topics
}

data "github_repository" "this" {
  count = var.create_repository ? 0 : 1

  full_name = var.repository
}

locals {
  repository_node_id   = var.create_repository ? github_repository.this[0].node_id : data.github_repository.this[0].node_id
  repository_full_name = var.create_repository ? github_repository.this[0].full_name : data.github_repository.this[0].full_name
  repository_html_url  = var.create_repository ? github_repository.this[0].html_url : data.github_repository.this[0].html_url

  # Branch list: protected_branches + optional release pattern (release/*)
  branches_to_protect = concat(
    var.protected_branches,
    var.protect_release_branch ? [var.release_branch_pattern] : []
  )
}

# ------------------------------------------------------------------------------
# Create 'develop' from default branch when repo is created and develop is protected
# (auto_init only creates default_branch; develop must exist to protect it)
# ------------------------------------------------------------------------------

resource "github_branch" "develop" {
  count = var.create_repository && contains(local.branches_to_protect, "develop") ? 1 : 0

  repository    = github_repository.this[0].name
  branch       = "develop"
  source_branch = var.default_branch
}

# =============================================================================
# Branch protection (main, develop, release/*)
# Enforces pull request rules: require PR, required reviews, conversation
# resolution, optional status checks. Release branches use same rules by default.
# =============================================================================

resource "github_branch_protection" "branch" {
  for_each = toset(local.branches_to_protect)

  repository_id = local.repository_node_id
  pattern       = each.value

  depends_on = [github_branch.develop]

  # Pull request rules: require PR and reviews before merging
  required_pull_request_reviews {
    dismiss_stale_reviews           = var.dismiss_stale_reviews
    require_code_owner_reviews      = var.require_code_owner_reviews
    required_approving_review_count = var.required_approving_review_count
  }

  # Require status checks (optional; omit when no checks configured for this branch)
  dynamic "required_status_checks" {
    for_each = length(try(var.required_status_checks[each.value], [])) > 0 ? [1] : []
    content {
      strict   = var.require_branches_up_to_date
      contexts = var.required_status_checks[each.value]
    }
  }

  # Safety: no force push, no branch deletion
  allows_force_pushes = var.allow_force_pushes
  allows_deletions    = var.allow_deletions

  # Linear history (squash/rebase only)
  required_linear_history = var.require_linear_history
  require_signed_commits  = var.require_signed_commits

  # Require conversation resolution (all PR comments resolved)
  require_conversation_resolution = var.require_conversation_resolution

  # Enforce for admins (no bypass)
  enforce_admins = var.enforce_admins

  # Lock branch (e.g. for archived release branches)
  lock_branch = var.lock_branch
}
