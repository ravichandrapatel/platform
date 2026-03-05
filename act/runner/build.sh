#!/usr/bin/env bash
# Build the custom act runner image (no public image). Tags act-runner:latest.
# Uses Docker or Podman; run from repo root or from devtools-landingzone/act/runner/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CTX="$REPO_ROOT"
FILE="$SCRIPT_DIR/Containerfile"

if command -v podman &>/dev/null; then
  RUNTIME=podman
elif command -v docker &>/dev/null; then
  RUNTIME=docker
else
  echo "Need Docker or Podman" >&2
  exit 1
fi

# Build from repo root so paths in COPY (if any) and act workspace match
cd "$REPO_ROOT"
"$RUNTIME" build -f "$FILE" -t act-runner:latest "$CTX"
echo "Built act-runner:latest with $RUNTIME"
