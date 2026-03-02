output "repository_id" {
  description = "GitHub repository node ID."
  value       = local.repository_node_id
}

output "repository_name" {
  description = "Repository full name (owner/name)."
  value       = local.repository_full_name
}

output "repository_html_url" {
  description = "URL to the repository on GitHub."
  value       = local.repository_html_url
}

output "protected_branch_patterns" {
  description = "List of branch patterns that have protection rules (main, develop, release/*)."
  value       = [for k, v in github_branch_protection.branch : v.pattern]
}

output "branch_protection_ids" {
  description = "Map of branch pattern to protection rule ID (for reference)."
  value       = { for k, v in github_branch_protection.branch : v.pattern => v.id }
}
