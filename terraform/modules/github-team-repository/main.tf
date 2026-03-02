# =============================================================================
# GitHub Team Repository (assignment) API
# =============================================================================
# Assigns teams to a repository with a permission via the GitHub "Add or update
# team repository permissions" API. The resource github_team_repository calls
# PUT /orgs/{org}/teams/{team_slug}/repos/{owner}/{repo} under the hood.
# Repository and teams must belong to the same organization.
# =============================================================================

locals {
  # Provider expects repository name (not full owner/name) when repo is in same org
  repository_name = try(split("/", var.repository)[1], var.repository)
}

resource "github_team_repository" "this" {
  for_each = { for a in var.team_assignments : a.team_id => a }

  team_id    = each.value.team_id
  repository = local.repository_name
  permission = each.value.permission
}
