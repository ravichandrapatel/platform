output "team_id" {
  description = "GitHub team ID (numeric)."
  value       = local.team_id
}

output "team_slug" {
  description = "GitHub team slug."
  value       = local.team_slug
}

output "team_node_id" {
  description = "GitHub team node ID (global ID)."
  value       = local.team_node_id
}

output "managed" {
  description = "True if the team is managed by this module (created or has managed marker); false if external."
  value       = local.should_manage
}

output "idp_sync_configured" {
  description = "True if IdP group sync is configured for this team (only when managed)."
  value       = local.should_manage && length(var.idp_groups) > 0
}

output "emu_mapping_configured" {
  description = "True if EMU external group mapping is configured (only when managed)."
  value       = local.should_manage && length(var.emu_group_ids) > 0
}
