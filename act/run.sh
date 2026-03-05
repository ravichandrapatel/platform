#!/usr/bin/env bash
# Run act from repo root with devtools-landingzone/.github as workflow directory.
# Usage: from repo root, ./devtools-landingzone/act/run.sh [OPTIONS] [WORKFLOW]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKFLOWS_DIR="$REPO_ROOT/devtools-landingzone/.github"
EVENT=workflow_dispatch
DRY_RUN=""
JOB=""
SECRET_FILE=""
SECRETS=()
WORKFLOW=""
USE_CUSTOM_IMAGE=1

# Custom act runner image (built with devtools-landingzone/act/runner/build.sh). No public image.
ACT_RUNNER_IMAGE="act-runner:latest"
# Podman uses localhost/ for local images when talking to Docker API
if command -v podman &>/dev/null && ! command -v docker &>/dev/null; then
  ACT_RUNNER_IMAGE="localhost/act-runner:latest"
fi

usage() {
  echo "Usage: $0 [OPTIONS] [WORKFLOW]"
  echo ""
  echo "Options:"
  echo "  -n, --dry-run       List jobs only, do not run"
  echo "  -j, --job NAME      Run only this job"
  echo "  -e, --event EV      Event (default: workflow_dispatch)"
  echo "  -s, --secret K=V    Pass secret (repeatable)"
  echo "  --secret-file F      Use F as .env-style secret file"
  echo "  --no-custom-image   Use default (public) runner image instead of local act-runner"
  echo ""
  echo "WORKFLOW: base name of workflow file without .yml (e.g. dependency-check-nightly)."
  echo "          Omit to list all workflows. Run from repo root: $REPO_ROOT"
  echo ""
  echo "Custom image: build with ./devtools-landingzone/act/runner/build.sh (required unless --no-custom-image)."
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run)        DRY_RUN="-n"; shift ;;
    -j|--job)            JOB="$2"; shift 2 ;;
    -e|--event)          EVENT="$2"; shift 2 ;;
    -s|--secret)         SECRETS+=(-s "$2"); shift 2 ;;
    --secret-file)       SECRET_FILE="$2"; shift 2 ;;
    --no-custom-image)  USE_CUSTOM_IMAGE=0; shift ;;
    -h|--help)           usage ;;
    -*)                  echo "Unknown option: $1"; usage ;;
    *)                   WORKFLOW="$1"; shift ;;
  esac
done

if [[ ! -d "$WORKFLOWS_DIR" ]]; then
  echo "Workflows dir not found: $WORKFLOWS_DIR" >&2
  exit 1
fi

# Act expects workflow files; we have .yml in devtools-landingzone/.github/
if [[ -n "$WORKFLOW" ]]; then
  WF_PATH="$WORKFLOWS_DIR/${WORKFLOW}.yml"
  if [[ ! -f "$WF_PATH" ]]; then
    echo "Workflow not found: $WF_PATH" >&2
    exit 1
  fi
  W_ARG=(-W "$WF_PATH")
else
  W_ARG=(-W "$WORKFLOWS_DIR")
fi

cd "$REPO_ROOT"
ACT_ARGS=("${W_ARG[@]}" --event "$EVENT")
[[ -n "$DRY_RUN" ]] && ACT_ARGS+=(-n)
[[ -n "$JOB" ]] && ACT_ARGS+=(-j "$JOB")
[[ -n "$SECRET_FILE" ]] && ACT_ARGS+=(--secret-file "$SECRET_FILE")
ACT_ARGS+=("${SECRETS[@]}")

if [[ "$USE_CUSTOM_IMAGE" -eq 1 ]]; then
  ACT_ARGS+=(-P "ubuntu-latest=$ACT_RUNNER_IMAGE" --pull=false)
fi

exec act "${ACT_ARGS[@]}"
