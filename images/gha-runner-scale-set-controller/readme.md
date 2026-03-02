# gha-runner-scale-set-controller (UBI9 controller)

Copies all controller binaries from the official [gha-runner-scale-set-controller](https://github.com/actions/actions-runner-controller) image (distroless) into **UBI9 minimal**: `manager`, `github-webhook-server`, `actions-metrics-server`, `ghalistener`, `sleep`. No build from source.

## Build

From this directory:

```bash
buildah build -t ghcr.io/YOUR_ORG/gha-runner-scale-set-controller:0.13.1 -f Containerfile .
# or
podman build -t ghcr.io/YOUR_ORG/gha-runner-scale-set-controller:0.13.1 -f Containerfile .
```

To use a different upstream tag:

```bash
podman build --build-arg CONTROLLER_TAG=0.13.0 -t ghcr.io/YOUR_ORG/gha-runner-scale-set-controller:0.13.0 -f Containerfile .
```

If the build fails on a `COPY` (e.g. file not found in upstream image), that tag may not include all five binaries; remove the corresponding `COPY` line in the Containerfile or try another tag.

## Use in ARC overlays

In **overlays/rosadev/controller-values.yaml** or **overlays/kubernetesdev/controller-values.yaml**, set the image to your UBI9 build:

```yaml
image:
  repository: ghcr.io/YOUR_ORG/gha-runner-scale-set-controller
  pullPolicy: IfNotPresent
  tag: "0.13.1"
```

Then run `make -C addons/arc generate` and apply as usual.
