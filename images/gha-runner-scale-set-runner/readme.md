# GitHub Actions Runner (UBI9 + ARC + Rootless Podman/Buildah)

Runner image for **[Actions Runner Controller (ARC)](https://github.com/actions/actions-runner-controller)**. Lives under **addons/arc/** next to the ARC overlays. **UBI9**, **rootless Podman/Buildah**, non-root **UID 1001 / GID 123** to match the OpenShift SCC (`overlays/rosadev/scc-github-arc.yaml`).

## Features

- **Under /home/runner** – Runner binary, k8s hooks, config in `/home/runner`. K8s hooks at `/home/runner/k8s/index.js`.
- **Non-root** – User `runner` UID **1001**, group **123** (matches ARC SCC). Sudo available so the runner does not hit forbidden errors.
- **Rootless Podman/Buildah** – subuid/subgid configured for user `runner`; use `podman` / `buildah` in workflows.

## SCC alignment (OpenShift)

The image is built for the ARC SCC in **overlays/rosadev/scc-github-arc.yaml**:

| SCC field           | Value        | Containerfile / pod                      |
|---------------------|-------------|------------------------------------------|
| runAsUser           | MustRunAs 1001 | User `runner` UID 1001                   |
| fsGroup             | MustRunAs 123  | Pod spec: fsGroup 123                    |
| supplementalGroups  | MustRunAs 123  | Pod spec: runAsGroup 123                |

- The container runs as **USER runner** (1001). Primary group of `runner` is GID 123.
- Pod **securityContext** in scale-set values: **runAsUser: 1001**, **runAsGroup: 123**, **fsGroup: 123**, **runAsNonRoot: true**.
- With that, the pod is allowed by the SCC and the process inside the container is 1001:123 with access to `/home/runner` and rootless Podman.

## Build (from repo root)

```bash
buildah build -t gha-runner-scale-set-runner:latest \
  --build-arg TARGETPLATFORM=linux/amd64 \
  -f devtools-landingzone/images/gha-runner-scale-set-runner/Containerfile \
  devtools-landingzone/images/gha-runner-scale-set-runner
```

Or with podman:

```bash
podman build -t gha-runner-scale-set-runner:latest \
  --build-arg TARGETPLATFORM=linux/amd64 \
  -f devtools-landingzone/images/gha-runner-scale-set-runner/Containerfile \
  devtools-landingzone/images/gha-runner-scale-set-runner
```

Optional build args: `RUNNER_VERSION`, `RUNNER_UID` (default 1001), `RUNNER_GID` (default 123), `SUBUID_COUNT` (default 100000).

## ARC scale set

1. Use this image as the runner image in the ARC scale set (e.g. in **overlays/rosadev/scale-set-values.yaml** or **overlays/kubernetesdev/scale-set-values.yaml**: `template.spec.containers[0].image`).
2. Pod **securityContext** must use **runAsUser: 1001**, **runAsGroup: 123**, **fsGroup: 123**, **runAsNonRoot: true** (already set in the overlay scale-set values).
3. On OpenShift, the runner pod service account must be bound to the **github-arc** SCC (ClusterRole + RoleBinding in the rosadev overlay).

## References

- [How to securely deploy GitHub ARC on OpenShift (Red Hat)](https://developers.redhat.com/articles/2025/02/17/how-securely-deploy-github-arc-openshift)
- [actions/actions-runner-controller](https://github.com/actions/actions-runner-controller)
- [actions/runner-container-hooks](https://github.com/actions/runner-container-hooks)
