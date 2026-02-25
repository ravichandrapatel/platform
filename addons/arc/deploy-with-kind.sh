#!/usr/bin/env bash
# Build the ARC runner image, push to GHCR, create a Kind cluster, and deploy the scale set.
# Requires: docker or podman, kind, kubectl, helm, GITHUB_TOKEN (PAT with repo, workflow, write:packages for push + ARC).
#
# Create a PAT at https://github.com/settings/tokens with:
#   - repo (full)
#   - workflow
#   - write:packages (push to ghcr.io; optional delete:packages)
#   For org runners add: admin:org
#
# Usage:
#   export GITHUB_TOKEN=ghp_xxxx
#   ./addons/arc/deploy-with-kind.sh
#
# Override registry/org (default: ghcr.io/ravichandrapatel/gha-runner-scale-set-runner:latest):
#   GITHUB_ORG=myorg REGISTRY_IMAGE=ghcr.io/myorg/gha-runner-scale-set-runner:latest ./addons/arc/deploy-with-kind.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNNER_CONTEXT="${PLATFORM_ROOT}/images/gha-runner-scale-set-runner"
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-arc}"
NAMESPACE="${NAMESPACE:-arc-system}"
CONTROLLER_CHART="oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller"
SCALE_SET_CHART="oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set"
CHART_VERSION="0.13.1"
VALUES="${SCRIPT_DIR}/overlays/kubernetesdev"

# Defaults from repo (ravichandrapatel/platform)
GITHUB_ORG="${GITHUB_ORG:-ravichandrapatel}"
REGISTRY_IMAGE="${REGISTRY_IMAGE:-ghcr.io/${GITHUB_ORG}/gha-runner-scale-set-runner:latest}"
GITHUB_CONFIG_URL="${GITHUB_CONFIG_URL:-https://github.com/${GITHUB_ORG}/platform}"

# Prefer docker; fall back to podman
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
  CONTAINER_CMD="docker"
elif command -v podman &>/dev/null; then
  CONTAINER_CMD="podman"
else
  echo "Error: docker or podman is required. Start Docker or install Podman." >&2
  exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Error: GITHUB_TOKEN is not set. Create a PAT at https://github.com/settings/tokens with repo, workflow, write:packages (and admin:org for org runners)." >&2
  exit 1
fi

echo "=== 1. Build runner image (${CONTAINER_CMD}) ==="
"${CONTAINER_CMD}" build \
  -f "${RUNNER_CONTEXT}/Containerfile" \
  --build-arg TARGETPLATFORM=linux/amd64 \
  -t "${REGISTRY_IMAGE}" \
  "${RUNNER_CONTEXT}"

echo "=== 2. Push to GHCR ==="
echo "$GITHUB_TOKEN" | "${CONTAINER_CMD}" login ghcr.io -u "${GITHUB_ORG}" --password-stdin
"${CONTAINER_CMD}" push "${REGISTRY_IMAGE}"

echo "=== 3. Kind cluster ==="
if kind get kubeconfig --name "${KIND_CLUSTER_NAME}" &>/dev/null; then
  echo "Kind cluster '${KIND_CLUSTER_NAME}' already exists."
else
  kind create cluster --name "${KIND_CLUSTER_NAME}"
fi
export KUBECONFIG="$(kind get kubeconfig --name "${KIND_CLUSTER_NAME}")"

echo "=== 4. Namespace and GitHub secret ==="
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic arc-gh-secret \
  -n "${NAMESPACE}" \
  --from-literal=github_token="${GITHUB_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "=== 5. Install ARC controller and scale set (Helm) ==="
helm upgrade --install arc-controller "${CONTROLLER_CHART}" \
  --version "${CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  --values "${VALUES}/controller-values.yaml"

helm upgrade --install arc-scale-set "${SCALE_SET_CHART}" \
  --version "${CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --values "${VALUES}/scale-set-values.yaml" \
  --set "githubConfigUrl=${GITHUB_CONFIG_URL}" \
  --set "template.spec.containers[0].image=${REGISTRY_IMAGE}"

echo "=== Done ==="
echo "Cluster: ${KIND_CLUSTER_NAME} (KUBECONFIG=$KUBECONFIG)"
echo "Runners will register for: ${GITHUB_CONFIG_URL}"
echo "Check pods: kubectl get pods -n ${NAMESPACE}"
echo "Scale up: set minRunners in scale-set-values and upgrade, or trigger a workflow to auto-scale."
