# Terraform plan policy for OPA stage.
# Add deny rules to block plans that violate policy; default allow.
package terraform.plan

default allow = true

# Example: deny if plan has no changes (optional; remove or customize)
# deny["plan has no changes"] { count(input.resource_changes) == 0 }
