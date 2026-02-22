# ARC (Actions Runner Controller) – production deployment

Production deployment for [Actions Runner Controller](https://github.com/actions/actions-runner-controller): **gha-runner-scale-set-controller** and **gha-runner-scale-set** (0.13.1).

## Layout

| Path | Purpose |
|------|--------|
| **base/** | Namespace `arc-system` and default Helm values (`controller-values.yaml`, `scale-set-values.yaml`). |
| **platform/images/gh-actions-runner-podman/** | Runner image (UBI9, non-root 1001:123). Build and use as the scale set runner image. See `platform/README.md` and `overlays/rosadev/scc-github-arc.yaml`. |
| **platform/images/gha-runner-scale-set-controller-ubi9/** | Controller image (UBI9 instead of distroless). Build and set `image` in overlay `controller-values.yaml` to use it. |
| **overlays/rosadev** | ROSA/OpenShift dev: SCC + ClusterRole + RoleBinding + controller + scale set (own values). |
| **overlays/kubernetesdev** | Plain Kubernetes dev: controller + scale set (own values). |
| **overlay-helm-rendered/** | Apply after `make generate` when OCI Helm is not available. |

## Values

- **base/** – Namespace and default Helm values for reference.
- **overlays/rosadev** – Uses `controller-values.yaml` and `scale-set-values.yaml` in that overlay. Edit those files for GitHub URL, runner image, resources, etc.
- **overlays/kubernetesdev** – Same: uses its own `controller-values.yaml` and `scale-set-values.yaml`. Edit per environment.

## Prerequisites

1. **GitHub auth** – Create secret in `arc-system`:
   ```bash
   kubectl create secret generic arc-gh-secret -n arc-system --from-literal=github_token='ghp_YOUR_PAT'
   ```
2. **Runner image** – Set in the overlay’s **scale-set-values.yaml** (`template.spec.containers[0].image`).

## Base and overlays

- **base/** – Shared namespace `arc-system` and default values (reference only).
- **overlays/rosadev** – ROSA / OpenShift dev: own values + SCC + ClusterRole + RoleBinding + controller + scale set.
- **overlays/kubernetesdev** – Plain Kubernetes dev: own values + controller + scale set.

### ROSA / OpenShift dev

1. Create secret: `oc create secret generic arc-gh-secret -n arc-system --from-literal=github_token='ghp_xxx'`
2. Edit **overlays/rosadev/scale-set-values.yaml** for `githubConfigUrl` and runner `image`.
3. Apply: `kubectl apply -k addons/arc/overlays/rosadev/`

The overlay includes SCC `github-arc`, ClusterRole, and RoleBinding. The RoleBinding grants the SCC to the scale set's service account (`arc-scale-set-gha-rs-no-permission` by default). **If you see "fsGroup 123 not allowed" or "not allowed by the SCC"**, ensure the runner pod's service account is in **overlays/rosadev/rolebinding-scc.yaml** `subjects` (same name/namespace). Optional: `oc policy add-role-to-user system:openshift:scc:github-arc -z arc-scale-set-gha-rs-no-permission -n arc-system`

**Dependency-check and rootless Podman:** The runner uses VFS storage and a custom SCC. Nested `podman run` (e.g. dependency-check) uses **`--cgroups=disabled`** so Podman does not create a child cgroup for the container; ROSA/unprivileged OpenShift blocks child cgroup creation (cgroups v2). The runner image sets `cgroups = "disabled"` in `~/.config/containers/containers.conf` by default. The runner container also uses `procMount: Unmasked` and capabilities SETUID/SETGID, SYS_ADMIN for newuidmap and proc mount. If you still see OCI permission denied, ensure the scale set and SCC are applied and runner pods were recreated.

**FUSE / fuse-overlayfs:** The scale set pod template includes the annotation `io.kubernetes.cri-o.Devices: "/dev/fuse"` so rootless Podman can use fuse-overlayfs (avoids "fuse device not found" / "fuse overlays cannot mount"). On OpenShift 4.15+ this is supported; on older versions the cluster may need CRI-O `allowed_devices` configured. If you cannot get `/dev/fuse` (e.g. on plain Kubernetes), add to the runner container env: `CONTAINERS_STORAGE_DRIVER: vfs` — storage will be slower but no FUSE is required.

### Kubernetes dev

1. Create secret: `kubectl create secret generic arc-gh-secret -n arc-system --from-literal=github_token='ghp_xxx'`
2. Edit **overlays/kubernetesdev/scale-set-values.yaml** for `githubConfigUrl` and runner `image`.
3. Apply: `kubectl apply -k addons/arc/overlays/kubernetesdev/`

### Without OCI Helm (generate then apply)

If your Kustomize has no OCI Helm support, render charts then apply:

1. Set `VALUES=overlays/kubernetesdev` or `VALUES=overlays/rosadev`, then edit that overlay’s values if needed.
2. `make -C addons/arc generate`
3. `kubectl apply -k addons/arc/overlay-helm-rendered/`

### Helm install (no Kustomize)

Use overlay values with Helm:

```bash
helm upgrade --install arc-controller oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
  --version 0.13.1 -n arc-system --create-namespace -f addons/arc/overlays/kubernetesdev/controller-values.yaml
helm upgrade --install arc-scale-set oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.13.1 -n arc-system -f addons/arc/overlays/kubernetesdev/scale-set-values.yaml
```

Use a pre-defined secret by setting `githubConfigSecret: arc-gh-secret` in the values (no inline `github_token`).

## References

- [How to securely deploy GitHub ARC on OpenShift (Red Hat Developer)](https://developers.redhat.com/articles/2025/02/17/how-securely-deploy-github-arc-openshift)
- [ARC – gha-runner-scale-set-controller](https://github.com/actions/actions-runner-controller/tree/master/charts/gha-runner-scale-set-controller)
- [ARC – gha-runner-scale-set](https://github.com/actions/actions-runner-controller/tree/master/charts/gha-runner-scale-set)
- [Deploying runner scale sets (GitHub Docs)](https://docs.github.com/en/actions/tutorials/use-actions-runner-controller/deploy-runner-scale-sets)
