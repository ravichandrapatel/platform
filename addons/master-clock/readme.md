# Master Clock (OpenShift GitHub Actions Trigger)

Python-based **Master Clock** for OpenShift that triggers GitHub Actions workflows with millisecond-precision intervals, bypassing unreliable GitHub native cron. Uses only the Python standard library.

## Features

- **Zero dependency:** `urllib.request`, `json`, `time`, `os`, `signal`
- **Config-driven:** Repository targets from `/etc/config/repos.json`
- **Token from ESO:** Reads GitHub token from `/etc/github/token` (dynamic token synced by External Secrets Operator)
- **February 2026 API:** Uses `return_run_details=true` on `workflow_dispatch`; captures `workflow_run_id` and `run_url` from the 200 OK JSON response for traceability
- **Stateful heartbeat:** On startup, polls `GET .../actions/runs` per repo to get the latest run `created_at`; maintains in-memory `last_fire_time` so restarts do not double-fire
- **Structured JSON logs** to stdout for OpenShift/Kibana; every trigger logs `workflow_run_id`
- **SIGTERM handling:** Graceful shutdown with a "Shutting down..." log

## Configuration

**Schema for `/etc/config/repos.json` (ConfigMap `master-clock-repos`):**

```json
{
  "app-name": {
    "owner": "org",
    "repo": "repo-name",
    "workflow_id": "workflow-file.yml",
    "interval_seconds": 900,
    "ref": "main",
    "inputs": {}
  }
}
```

- `workflow_id`: Workflow filename (e.g. `drift-check.yml`) or numeric ID
- Optional: `ref` – git ref for workflow_dispatch (default: env `GITHUB_REF_NAME` or `main`)
- Optional: `inputs` – object of workflow_dispatch inputs

Config is reloaded when the file mtime changes (e.g. ConfigMap update). Token is re-read every 10 minutes so ESO rotation is picked up. Failed dispatches are retried 3 times with 5s backoff.

## Architecture

1. **Trigger app** (`trigger_app.py`) runs as a single-replica Deployment.
2. **Config:** ConfigMap `master-clock-repos` → mount at `/etc/config/repos.json`.
3. **Token:** ESO-synced secret `github-token` (format `kubernetes.io/basic-auth`, username `x-access-token`) → mount password at `/etc/github/token`.
4. **ESO:** ClusterGenerator `github-token-generator` (GitHub App) + ClusterExternalSecret `ocp-token-sync` (refresh 25m, namespaces with label `type: ci-pipeline`).

## ESO Setup

1. **GitHub App PEM**  
   Create a Secret named `github-app-pem` with key `key` (PEM content) in every namespace that has label `type: ci-pipeline` (including `master-clock`). Use `manifests/eso-github-app-pem-secret.yaml` as a template or sync from Vault via your own ExternalSecret.

2. **ClusterGenerator**  
   Edit `manifests/eso-cluster-generator-github-token.yaml`: set `appID` and `installID`, then apply. The generator references `github-app-pem` in the same namespace as the created ExternalSecret.

3. **ClusterExternalSecret**  
   Apply `manifests/eso-cluster-external-secret-ocp-token-sync.yaml`. It creates a Secret `github-token` (basic-auth, username `x-access-token`) in all namespaces with label `type: ci-pipeline`, refreshed every 25 minutes.

## Deployment (OpenShift)

1. Install External Secrets Operator and ensure the GitHub App PEM is available (see above).
2. Build and push the trigger image (e.g. from this repo with `trigger_app.py` in `/app`):
   ```dockerfile
   FROM python:3.11-slim
   COPY addons/master-clock/trigger_app.py /app/
   WORKDIR /app
   CMD ["python3", "trigger_app.py"]
   ```
3. Create the namespace and ConfigMap, then apply the Deployment:
   ```bash
   kubectl apply -f platform/addons/master-clock/manifests/namespace.yaml
   kubectl apply -f platform/addons/master-clock/manifests/configmap-repos.yaml
   # After ESO has created github-token in master-clock:
   kubectl apply -f platform/addons/master-clock/manifests/deployment.yaml
   ```
   Or use Kustomize: from `platform/addons/master-clock`, run `kubectl apply -k .` (after uncommenting ESO resources in `kustomization.yaml` and configuring the generator).

## Health

HTTP server on port 8080 (override with `HEALTH_PORT`):

- `GET /`, `/health`, `/ready`, `/live` – 200 when token and config are loaded and loop is running; 503 otherwise.

Use `/ready` for readiness and `/live` for liveness in Kubernetes.

## Logging

All output is JSON to stdout, e.g.:

```json
{"level": "info", "message": "triggered", "ts": 1739..., "app_name": "drift-audit", "owner": "my-org", "repo": "my-repo", "workflow_id": "drift-check.yml", "workflow_run_id": 123456789, "run_url": "https://api.github.com/...", "html_url": "https://github.com/..."}
```

Use `workflow_run_id` and `run_url` for end-to-end traceability in Kibana or your log aggregator.

## API Reference (Feb 2026)

- **Trigger:** `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches?return_run_details=true`  
  Body: `{"ref": "main", "inputs": {...}}`.  
  Returns **200 OK** with JSON: `workflow_run_id`, `run_url`, `html_url` (no longer 204 No Content when `return_run_details=true`).
- **State init:** `GET /repos/{owner}/{repo}/actions/runs?per_page=5` to get latest run `created_at` for `last_fire_time`.
