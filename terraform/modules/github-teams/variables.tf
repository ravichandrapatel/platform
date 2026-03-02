# ------------------------------------------------------------------------------
# Optional: pass org teams from root to avoid one API call per module instance
# ------------------------------------------------------------------------------
# When you use multiple github-teams modules in the same config, each one
# fetches data.github_organization_teams. Pass the result from root once:
#   data "github_organization_teams" "all" {}
#   module "team_a" { ... organization_teams = data.github_organization_teams.all.teams }
#   module "team_b" { ... organization_teams = data.github_organization_teams.all.teams }
# This reduces GitHub API calls (helps avoid rate limits in CI).
# ------------------------------------------------------------------------------

variable "organization_teams" {
  description = "Optional. Pass data.github_organization_teams.<name>.teams from root to avoid one API call per module instance (use when you have multiple github-teams modules in the same config)."
  type        = list(any)
  default     = null
}

# ------------------------------------------------------------------------------
# Deploying repository (repo-bound marker)
# ------------------------------------------------------------------------------

variable "repository" {
  description = "Repository that owns this deployment, in the form 'owner/name' (e.g. my-org/infra-repo). The managed marker in the team description includes this so only this repo's runs will manage the team; if the team was created by a different repo, it is treated as external."
  type        = string
}

# ------------------------------------------------------------------------------
# Team identity: slug is used to look up existing teams; name is used when creating
# ------------------------------------------------------------------------------

variable "team_slug" {
  description = "Team slug (e.g. platform-eng). Required for data lookup and for sync/EMU. When creating a team, slug is derived from name unless you use a name that produces this slug."
  type        = string
}

variable "team_name" {
  description = "Display name of the team. Used when the module creates the team; defaults to team_slug if empty."
  type        = string
  default     = ""
}

variable "team_description" {
  description = "Description of the team. When the module manages the team, a managed marker is appended so it can be recognized as managed on the next run."
  type        = string
  default     = ""
}

variable "privacy" {
  description = "Team privacy: 'secret' or 'closed'."
  type        = string
  default     = "closed"
}

# ------------------------------------------------------------------------------
# Parent team (optional; only when the module manages the team)
# ------------------------------------------------------------------------------

variable "parent_team_id" {
  description = "ID of the parent team (for nested teams). Only used when the module creates/updates the team."
  type        = string
  default     = null
}

# ------------------------------------------------------------------------------
# IdP group sync (GitHub OIDC / Azure OIDC / SAML). Only when manage_team = true
# ------------------------------------------------------------------------------

variable "idp_groups" {
  description = "List of IdP groups to sync to this team. Each object: group_id, group_name, group_description. Only applied when the module manages the team. Leave empty to not manage sync."
  type = list(object({
    group_id          = string
    group_name        = string
    group_description = string
  }))
  default = []
}

# ------------------------------------------------------------------------------
# EMU (Enterprise Managed Users) external group mapping
# ------------------------------------------------------------------------------

variable "emu_group_ids" {
  description = "List of EMU external group IDs to map to this team. Only applied when the module manages the team. Leave empty to not manage EMU mapping."
  type        = list(string)
  default     = []
}
