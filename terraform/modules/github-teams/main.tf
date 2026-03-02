# =============================================================================
# Repo-bound managed vs external: use Terraform data only (no external script).
# - Fetch all org teams (or use var.organization_teams from root to avoid N API calls).
# - Find this one by slug; if not found -> manage (create); if found with our marker -> manage; else external.
# =============================================================================

data "github_organization_teams" "all" {
  count = var.organization_teams != null ? 0 : 1
}

locals {
  # Use passed-in teams from root (one API call for many modules) or fetch here
  all_teams = var.organization_teams != null ? var.organization_teams : data.github_organization_teams.all[0].teams

  # Marker is repo-bound: only this repository's runs will consider the team managed
  managed_marker = "Managed by Terraform: github-teams module (repo: ${var.repository})"

  # Find this team in the org (null if not found)
  existing_team = try(
    [for t in local.all_teams : t if t.slug == var.team_slug][0],
    null
  )

  # Team exists and its description contains the marker for THIS repo (same repo = we own it)
  has_managed_marker_for_this_repo = local.existing_team != null && strcontains(
    coalesce(local.existing_team.description, ""),
    local.managed_marker
  )

  # Manage only when: team does not exist (create) OR team exists with our repo's marker (update/sync)
  should_manage = local.existing_team == null || local.has_managed_marker_for_this_repo

  managed_description_suffix = " ${local.managed_marker}"
  managed_description        = trimspace(var.team_description) != "" ? "${var.team_description}${local.managed_description_suffix}" : trimspace(local.managed_marker)
}

# ------------------------------------------------------------------------------
# Team: create or update only when should_manage (team missing or has marker)
# If team already exists with marker but is not in state, import it first.
# ------------------------------------------------------------------------------

resource "github_team" "this" {
  count = local.should_manage ? 1 : 0

  name            = coalesce(trimspace(var.team_name), var.team_slug)
  description     = local.managed_description
  privacy         = var.privacy
  parent_team_id  = var.parent_team_id
}

# ------------------------------------------------------------------------------
# Resolved team slug, id, node_id (from resource when managed, from list when external)
# ------------------------------------------------------------------------------

locals {
  team_slug   = local.should_manage ? github_team.this[0].slug : local.existing_team.slug
  team_id     = local.should_manage ? github_team.this[0].id : tostring(local.existing_team.id)
  team_node_id = local.should_manage ? github_team.this[0].node_id : local.existing_team.node_id
}

# =============================================================================
# IdP group sync and EMU mapping: only when we manage the team
# =============================================================================

resource "github_team_sync_group_mapping" "this" {
  count = local.should_manage && length(var.idp_groups) > 0 ? 1 : 0

  team_slug = local.team_slug

  dynamic "group" {
    for_each = var.idp_groups
    content {
      group_id          = group.value.group_id
      group_name        = group.value.group_name
      group_description = group.value.group_description
    }
  }
}

resource "github_emu_group_mapping" "this" {
  for_each = local.should_manage && length(var.emu_group_ids) > 0 ? toset(var.emu_group_ids) : toset([])

  team_slug = local.team_slug
  group_id  = each.value
}
