# ------------------------------------------------------------------------------
# Team repository assignment outputs
# ------------------------------------------------------------------------------

output "team_repository_ids" {
  description = "Map of team_id to github_team_repository resource ID (team_id:repository)."
  value       = { for k, r in github_team_repository.this : k => r.id }
}

output "permissions" {
  description = "Map of team_id to permission (pull, push, maintain, admin, triage)."
  value       = { for k, r in github_team_repository.this : k => r.permission }
}
