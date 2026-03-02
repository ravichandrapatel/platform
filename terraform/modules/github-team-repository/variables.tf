# ------------------------------------------------------------------------------
# Repository to assign teams to
# ------------------------------------------------------------------------------

variable "repository" {
  description = "Repository in the form 'owner/name' (e.g. my-org/my-repo). Must exist and belong to the same organization as the teams."
  type        = string
}

# ------------------------------------------------------------------------------
# Team assignments: list of team ID + permission
# ------------------------------------------------------------------------------
# team_id comes from github_team.id or from the github-teams module output (team_id).
# permission: pull (read), push (write), maintain, admin, or triage.
# ------------------------------------------------------------------------------

variable "team_assignments" {
  description = "List of team assignments. Each item: team_id (string, from github_team.id or module.github_teams.team_id) and permission (pull, push, maintain, admin, triage)."
  type = list(object({
    team_id    = string
    permission = string
  }))
  default = []

  validation {
    condition = alltrue([
      for a in var.team_assignments :
      contains(["pull", "push", "maintain", "admin", "triage"], a.permission)
    ])
    error_message = "Each team_assignments.permission must be one of: pull, push, maintain, admin, triage."
  }
}
