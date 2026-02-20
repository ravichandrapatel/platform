# ARC: render Helm charts to YAML for use with Kustomize (overlay-helm-rendered).
# Requires: helm
# Usage: make generate  then  kubectl apply -k addons/arc/overlay-helm-rendered/
# Values from an overlay (overlays/kubernetesdev or overlays/rosadev). Override with VALUES=overlays/rosadev etc.

HELM ?= helm
CONTROLLER_CHART ?= oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
SCALE_SET_CHART ?= oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
VERSION ?= 0.13.1
NAMESPACE ?= arc-system
VALUES ?= overlays/kubernetesdev

.PHONY: generate clean install

generate: manifests/controller.yaml manifests/scale-set.yaml

manifests:
	@mkdir -p manifests

manifests/controller.yaml: manifests $(VALUES)/controller-values.yaml
	$(HELM) template arc-controller $(CONTROLLER_CHART) \
		--version $(VERSION) \
		--namespace $(NAMESPACE) \
		--values $(VALUES)/controller-values.yaml \
		> manifests/controller.yaml

manifests/scale-set.yaml: manifests $(VALUES)/scale-set-values.yaml
	$(HELM) template arc-scale-set $(SCALE_SET_CHART) \
		--version $(VERSION) \
		--namespace $(NAMESPACE) \
		--values $(VALUES)/scale-set-values.yaml \
		> manifests/scale-set.yaml

clean:
	rm -rf manifests

# Install via Helm (values from VALUES overlay)
install-controller:
	$(HELM) upgrade --install arc-controller $(CONTROLLER_CHART) \
		--version $(VERSION) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--values $(VALUES)/controller-values.yaml

install-scale-set: install-controller
	$(HELM) upgrade --install arc-scale-set $(SCALE_SET_CHART) \
		--version $(VERSION) \
		--namespace $(NAMESPACE) \
		--values $(VALUES)/scale-set-values.yaml
