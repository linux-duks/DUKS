# DUKS Helm chart

Deploys DUKS (the Flask/gunicorn API and the static frontend) on Kubernetes.
The chart reproduces the production compose stack (`../compose.yaml`):

| Component | What it is |
|-----------|------------|
| `api` | Backend (`server/Containerfile.prod`, gunicorn on port 6000) + the static frontend baked into the same image |
| `nginx` | Reverse proxy and static file server. The static files are copied out of the **api image** by an initContainer, so there is only one image to build and push |
| `tunnel` | **Optional** generic sidecar in the nginx pod (cloudflared, ngrok, ...). The alternative to exposing the release through an Ingress |
| data volume | PVC (default) or an existing NFS export, mounted at `/data` in the api pod |

## Install

```bash
# 1. build and push the API image (from the repository root)
make image-build IMAGE_REGISTRY=ghcr.io/linux-duks IMAGE_TAG=latest
make image-push  IMAGE_REGISTRY=ghcr.io/linux-duks IMAGE_TAG=latest

# 2. install
make chart-install NAMESPACE=duks RELEASE=duks

# 3. load the dataset into the volume
make data-sync NAMESPACE=duks
```

Or with plain Helm:

```bash
helm upgrade --install duks ./chart --namespace duks --create-namespace \
  --set api.image.repository=ghcr.io/linux-duks/duks-server \
  --set api.image.tag=latest
```

Check the result without touching a cluster:

```bash
helm lint ./chart
helm template duks ./chart --namespace duks
```

## Storage

The `data/` folder of this repository (see the root README) is **not** part of
the image or the chart; it is mounted into the api pod. Two options:

**PVC (default)** — the chart creates a `PersistentVolumeClaim`:

```yaml
persistence:
  enabled: true
  type: pvc
  mountPath: /data
  pvc:
    storageClassName: ""   # empty => cluster default StorageClass
    size: 10Gi
    accessMode: ReadWriteOnce
```

The api Deployment uses `strategy: Recreate`, because a `ReadWriteOnce` claim
cannot be attached to two pods at once. Keep `api.replicaCount: 1` unless you
switch to `ReadWriteMany` on a storage class that supports it.

**NFS** — no PVC is created, the api pod mounts an existing export:

```yaml
persistence:
  enabled: true
  type: nfs
  mountPath: /data
  nfs:
    server: nfs.example.tld
    path: /exports/duks
```

`persistence.enabled: false` mounts an `emptyDir` instead. The dashboards then
return errors until data is copied in, and the data disappears with the pod —
useful only for smoke tests.

## Loading the data

`make data-sync` copies the local `./data` folder into the running api pod's
data volume:

```bash
make data-sync NAMESPACE=duks
```

It resolves the api pod through the chart's component labels
(`app.kubernetes.io/name=duks,app.kubernetes.io/component=api`), creates the
mount path, and runs `kubectl cp ./data/. <pod>:/data/`. It needs the api pod to
be running, and it re-copies the whole folder on each run — for very large
datasets prefer a one-shot loader Job or an NFS export.

Override the pieces when needed:

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_DIR` | `./data` | Local folder to copy |
| `POD_DATA_PATH` | `/data` | Mount path inside the pod (`persistence.mountPath`) |
| `API_POD_SELECTOR` | `app.kubernetes.io/name=duks,app.kubernetes.io/component=api` | Pod selector used to find the api pod |
| `NAMESPACE` | `duks` | Release namespace |
| `KUBECTL` | `kubectl` | kubectl binary |

## Exposing DUKS

Two mutually exclusive strategies; both are off by default.

### Ingress

```yaml
ingress:
  enabled: true
  className: nginx          # your IngressClass, empty => cluster default
  host: duks.example.tld    # required when enabled
  annotations: {}
  tls:
    - secretName: duks-tls
      hosts:
        - duks.example.tld
```

The Ingress sends `/` to the nginx Service on port 80.

### Tunnel sidecar

Use this when the cluster has no ingress controller or the service must be
reached through an outbound tunnel. The chart stays provider agnostic: it runs
whatever image/command/env you supply, next to nginx in the same pod, and the
tunnel reaches nginx over `localhost:80`.

```yaml
tunnel:
  enabled: true
  image: docker.io/cloudflare/cloudflared:latest
  command: ["tunnel", "run"]
  # Keep secrets out of values.yaml: mount them with envFrom instead of env.
  envFrom:
    - secretRef:
        name: duks-tunnel            # kubectl create secret generic duks-tunnel --from-literal=TUNNEL_TOKEN=...
  # env:
  #   - name: TUNNEL_TOKEN
  #     value: "..."
```

`tunnel.image` and `tunnel.command` are required when `tunnel.enabled` is true,
and `helm template` fails loudly if either is missing. The chart creates no
Service or probes for the tunnel; it is a plain sidecar.

## Values reference

| Key | Default | Notes |
|-----|---------|-------|
| `api.image.repository` / `.tag` | `ghcr.io/linux-duks/duks-server` / `latest` | Image built by `make image-build` |
| `api.replicaCount` | `1` | Keep at 1 for `ReadWriteOnce` PVCs |
| `api.port` | `6000` | gunicorn bind / Service port |
| `api.command` / `api.args` | `[]` | Empty => `gunicorn app:app -w 4 --threads 4 -b 0.0.0.0:6000` |
| `api.probes.*` | enabled | HTTP probes on `/` |
| `nginx.image.repository` / `.tag` | `docker.io/nginx` / `1.31-alpine` | Same image as compose |
| `persistence.*` | PVC, `/data`, 10Gi | See [Storage](#storage) |
| `ingress.*` | disabled | See [Ingress](#ingress) |
| `tunnel.*` | disabled | See [Tunnel sidecar](#tunnel-sidecar) |
| `serviceAccount.create` | `true` | One ServiceAccount shared by both pods |
| `imagePullSecrets` | `[]` | List of `{name: ...}` for private registries |

## How the pieces fit

```
Ingress (optional) ─┐
tunnel sidecar   ───┴─> nginx Service :80 ─> nginx pod
                                             ├─ /www/data (emptyDir, filled by the copy-static initContainer from the api image)
                                             └─ /api -> <release>-duks-api:6000

api Service :6000 ─> api pod ─> /data (PVC or NFS) ─> kernel/, knowledge_map/
```

The nginx config lives in [`files/nginx.conf`](files/nginx.conf) and is shipped
as a ConfigMap; `__API_UPSTREAM__` is replaced with this release's api Service
at render time. It is the same config as `../nginx/nginx.conf`, minus the
compose-only `listen 18000;`.

The `copy-static` initContainer uses `cp -R`, not `cp -a`. The volume it writes
to (`emptyDir`) is owned by root while the container runs as the api image's
`USER 1000`, so `cp -a`'s attempt to restore ownership/timestamps on the
destination directory fails with `Operation not permitted`, exits 1, and leaves
the nginx pod stuck in `Init:Error`. As a consequence the copied files carry the
pod's start time as mtime, so browsers revalidate static assets after a restart
(they then get a fresh 200 instead of a 304). That only affects caching, not
content.
