# GitHub Teams Module

Create or reference GitHub teams and optionally manage **IdP group sync** (GitHub OIDC / Azure OIDC / SAML) and **EMU (Enterprise Managed Users) external group mapping**. Uses the [integrations/github](https://registry.terraform.io/providers/integrations/github/latest) provider **~> 6.11**.

**Managed vs external is automatic and repo-bound**: the module uses Terraform data only and a marker that includes the **deploying repository** name.

## Repo-bound behavior (Terraform only)

You pass **`repository`** (e.g. `my-org/infra-repo`) — the repo that owns this Terraform. The marker written into the team description is:

`Managed by Terraform: github-teams module (repo: owner/name)`

The module uses `data.github_organization_teams` to list org teams and find this one by `team_slug`. It then:

1. **Team does not exist** → **Manage**: create the team with that marker (including your `repository`), and apply IdP/EMU if provided.
2. **Team exists and description contains the marker for this repo** → **Manage**: same repo owns it; update the team and apply IdP/EMU (team may need to be [imported](#importing-an-existing-managed-team) into state if it was created in another run).
3. **Team exists but marker is for a different repo** → **Do not manage**: deployed by another repo; treat as external and do not create or update.
4. **Team exists and description has no marker** → **Do not manage**: treat as external.

So each team is bound to one repository. If another repo’s Terraform created the team (or the marker was set by hand to another repo), this run will ignore it. No Python or external script—logic is entirely in the Terraform module.

## Importing an existing managed team

If the team already exists and its description already contains the marker **for this repo** (e.g. `(repo: my-org/infra-repo)`), you must **import** it so this state can update it:

```bash
terraform import 'module.my_team.github_team.this[0]' <team_slug>
```

After import, the module will manage updates and sync/EMU as usual.

## Usage

### New team (module will create it)

```hcl
module "platform_team" {
  source = "../../modules/github-teams"

  repository       = "my-org/infra-repo"   # repo that owns this Terraform (marker is repo-bound)
  team_slug        = "platform-eng"
  team_name        = "Platform Engineering"
  team_description = "Owns platform tooling and infra"

  idp_groups = [
    {
      group_id          = "abc-123"
      group_name        = "Platform Eng"
      group_description = "Azure AD / GitHub OIDC group"
    }
  ]

  emu_group_ids = ["external-group-uuid-1"]
}
```

### Existing external team (module will not create or change it)

Use the same module and pass the existing team’s slug and your `repository`. If the team exists with no marker or with a marker for a **different** repo, the module will not create or update it. Outputs still work.

```hcl
module "external_team" {
  source = "../../modules/github-teams"

  repository = "my-org/infra-repo"
  team_slug  = "existing-team-slug"
}
```

### Team without IdP or EMU

```hcl
module "team" {
  source = "../../modules/github-teams"

  repository       = "my-org/infra-repo"
  team_slug        = "my-team"
  team_name        = "My Team"
  team_description = "Description"
}
```

### Multiple teams in one config (fewer API calls)

Use one `data.github_organization_teams` at root and pass `.teams` into each module so the provider fetches org teams only once per plan instead of once per module:

```hcl
data "github_organization_teams" "all" {}

module "platform_team" {
  source = "../../modules/github-teams"

  repository        = "my-org/infra-repo"
  organization_teams = data.github_organization_teams.all.teams
  team_slug         = "platform-eng"
  team_name         = "Platform Engineering"
}

module "backend_team" {
  source = "../../modules/github-teams"

  repository        = "my-org/infra-repo"
  organization_teams = data.github_organization_teams.all.teams
  team_slug         = "backend-eng"
  team_name         = "Backend Engineering"
}
```

## Inputs

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `repository` | `string` | (required) | Repo that owns this deployment (owner/name). Marker in team description is repo-bound so only this repo’s runs manage the team. |
| `team_slug` | `string` | (required) | Slug to find or create (e.g. platform-eng). |
| `organization_teams` | `list(any)` | `null` | **Optional.** Pass `data.github_organization_teams.<name>.teams` from root to avoid one API call per module (use when you have multiple github-teams modules in the same config). |
| `team_name` | `string` | `""` | Display name when the module creates the team; defaults to team_slug. |
| `team_description` | `string` | `""` | Description; when managed, the managed marker is appended. |
| `privacy` | `string` | `"closed"` | `secret` or `closed`. |
| `parent_team_id` | `string` | `null` | Parent team ID for nested teams (when managed). |
| `idp_groups` | `list(object)` | `[]` | IdP groups for team sync (when managed). |
| `emu_group_ids` | `list(string)` | `[]` | EMU external group IDs (when managed). |

## Outputs

| Name | Description |
|------|-------------|
| `team_id` | GitHub team ID. |
| `team_slug` | Team slug. |
| `team_node_id` | Team node ID. |
| `managed` | Whether the module is managing this team. |
| `idp_sync_configured` | Whether IdP sync is configured. |
| `emu_mapping_configured` | Whether EMU mapping is configured. |

## Authentication

Use a GitHub token (PAT or GitHub App) with `read:org` and `write:org` (or `admin:org`). The provider must have `owner` (organization) set so `github_organization_teams` can list teams.

## GitHub API rate limits

- **Unauthenticated:** 60 requests/hour. **Authenticated (PAT):** 5,000/hour. **GitHub App:** 5,000/hour per installation (recommended for CI).
- To avoid hitting limits when running Terraform plan across many workspaces or repos:
  1. **Skip refresh in CI:** Use `-refresh=false` on `terraform plan` so data sources are read from state instead of the API. Run a scheduled job (e.g. `terraform apply -refresh-only`) once per day to refresh state; see the repo’s Terraform CI docs (e.g. “Data source refresh (daily cache)”).
  2. **Pass org teams from root:** When using multiple `github-teams` modules in the same config, set `organization_teams = data.github_organization_teams.<name>.teams` so the API is called once per plan instead of once per module.
  3. **Use a GitHub App in CI:** Prefer a GitHub App token over a PAT for higher and more predictable rate limits.
