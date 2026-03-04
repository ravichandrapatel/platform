# Issues Bot

Idempotent GitHub Action for creating, updating, closing, or upserting issues with **tracking-ID deduplication**, **rate-limit resilience**, and optional labels. Stdlib-only Python; outputs `issue-number` and `issue-url` to `GITHUB_OUTPUT`.

## Features

- **State & idempotency**: Deduplication by tracking ID (stored in a hidden HTML comment in the issue body). Find existing issues before creating.
- **Modes**: `create`, `update`, `close`, `upsert` (update if found, else create).
- **Primary rate limiting**: Pauses when `X-RateLimit-Remaining` ≤ 50 until reset (cleaner than 403 in logs).
- **Secondary rate limiting**: 0.1–0.2 s delay before POST/PATCH/DELETE (configurable via `ISSUES_BOT_DESTRUCTIVE_DELAY`).
- **Pagination**: All list requests use `per_page=100` and `page=N`.
- **Smart body**: Standardized footer `<!-- issues-bot:id:TRACKING_ID -->` so the bot can find its own issues even if the title changes. Support variable injection from the workflow (e.g. `${{ github.run_id }}`, `${{ github.actor }}` in `issue-body`).

## Required permissions

| Permission   | Scope        | Reason                    |
|-------------|--------------|---------------------------|
| Issues      | **write**    | Create, edit, close issues |
| Metadata    | **read**     | Repository details        |
| Pull Requests | **read** (optional) | If issues reference PRs |

## Inputs

| Input         | Required | Description |
|---------------|----------|-------------|
| `mode`        | Yes      | `create`, `update`, `close`, or `upsert` |
| `issue-title` | Yes      | Title for the issue |
| `tracking-id` | Yes      | Unique string for deduplication (stored in body footer) |
| `issue-body`  | No       | Markdown body; footer with tracking ID is appended |
| `labels`      | No       | Comma-separated labels to apply |
| `repo`        | No       | `owner/repo` or name (default: `github.repository`) |
| `github_token`| No       | Default: `github.token` |

## Outputs

| Output       | Description |
|--------------|-------------|
| `issue-number` | Issue number (when created or found/updated) |
| `issue-url`    | Issue HTML URL |

## Upsert logic

1. **Search**: `GET /repos/{owner}/{repo}/issues?state=open&per_page=100&page=N` (paginated).
2. **Filter**: Find an issue whose body contains the tracking ID (hidden comment or plain).
3. **Decision**: If found → `PATCH` body (and optional title/labels). If not found → `POST` to create.
4. **Output**: Write `issue-number` and `issue-url` to `GITHUB_OUTPUT`.

## Example

```yaml
- name: Upsert drift issue
  id: issue
  uses: ./platform/actions/issues-bot
  with:
    mode: upsert
    issue-title: "Infrastructure drift detected"
    tracking-id: "drift-report-main"
    issue-body: |
      Drift detected in run ${{ github.run_id }}.
      Actor: ${{ github.actor }}
    labels: "automation,drift"
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

- name: Use output
  run: echo "Issue #${{ steps.issue.outputs.issue-number }}"
```

## Environment (optional)

- `ISSUES_BOT_DESTRUCTIVE_DELAY`: Delay in seconds (0.1–0.2) before destructive API calls. Default `0.15`.
- `ISSUES_BOT_BODY`: Fallback body if `--issue-body` is not provided.
- `ISSUES_BOT_TRACKING_PREFIX`: Prefix for the hidden footer tag (default `issues-bot:id`). Body footer is `<!-- {prefix}:{tracking_id} -->`.
- `ISSUES_BOT_CREATOR_FILTER`: When listing issues, filter by creator (e.g. `github-actions[bot]`) for faster search. Default `github-actions[bot]`. Set to empty to disable.
