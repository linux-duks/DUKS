# 🦆 DUKS - Dashboard for Unified Kernel Statistics

How is the Linux Kernel development going ? Duks is a [work in progress] data visualization tool to help with that.

[duks.rcpassos.me](https://duks.rcpassos.me)

## Development

To run DUKS in development, it is recommended to use the `dev-compose.yaml` file.
This starts the server with the Backend (that also serves the Frontend).

```bash
podman-compose -f dev-compose.yaml up
```

Obtain the sample data files in the archived [replication package](https://archive.softwareheritage.org/browse/origin/directory/?origin_url=https://github.com/linux-duks/DUKS-2025-replication-pkg).

The file structure

```
├── data                  -> where the data files should be stored
│   ├── kernel            -> Kernel dashboard exports (parquet + CSV)
│   └── knowledge_map     -> per-repository node CSVs for the treemap (see below)
├── nginx                 -> configurations for nginx (for production)
├── scripts               -> scripts used to generate the dataset
└── server                -> backend source code
    ├── app.py            -> shared app shell (registers the module blueprints)
    ├── data_dirs.py      -> the one place that maps a module to its data folder
    ├── kernel/           -> Kernel dashboard module (loaders + /api/commits, /api/tags)
    ├── knowledge_map/    -> treemap module (/api/knowledge-map/*)
    └── static            -> static Frontend files
        └── knowledge-map -> the Knowledge Distribution Treemap page (/knowledge-map)
```

Every module reads its data from its own folder under `data/`; modules never
build data paths themselves. `data_dirs.module_data_dir(<module>)` resolves
`<data root>/<module>`, and the data root is the repository's `data/` directory
unless the `DATA_DIR` environment variable points elsewhere (the containers set
it to `/data`, where the data volume is mounted).

### Tests

The server tests live in `server/tests` and run inside the server project, so
the application modules import exactly as they do under gunicorn:

```bash
cd server && uv run pytest
```

The repository-level `pyrightconfig.json` points Pyright at `server/.venv`
(created by `uv sync`), so imports resolve in type-checkers and editors.

## Dashboards

- **Kernel Statistics Dashboard** (`/dashboard`) — contributor and lines-of-code
  time series over the kernel's history.
- **Knowledge Distribution Treemap** (`/knowledge-map`) — a nested treemap of a
  codebase where each rectangle's area is how much code a file or folder holds
  and its colour is its Pony Factor
  (how few authors wrote most of that code). It reads per-repository CSVs from
  `data/knowledge_map/*.csv`; each row is one node with at least the columns
  `identifier`, `pony_factor`, `node_len_lines`, `node_name` (separated by `·`
  in the per-project exports, or `,` in the `tokenFilesFull` token dump). These
  files are not committed — obtain them from the treemap replication package.
  The `_all_projects.csv` aggregate, if present, is ignored.

## Running from zero

Bootstrapping this from zero requires a few external resources.

Requirements:

- Local compressed Software Heritage Graph (at least “History and hosting” graph: 1.4TiB for 2024-12-06) : <https://docs.softwareheritage.org/devel/swh-export/graph/index.html>
- Linux kernel mainline tree
- Software heritage GRPC server: <https://docs.softwareheritage.org/devel/swh-graph/grpc-api.html#starting-the-server>

### Preparing the dataset

This repository is organized to use `uv` as its python dependencies, this document will use it.
Run scripts from the project root directory (as it will create a `./data/kernel/` folder relative to the scripts).
Other options should work.

1. run the GRPC server with the local graph, following the upstream guide.
  Example: `swh-graph-grpc-serve --bind 0.0.0.0:50091 /media/research/2025-05-18-history-hosting/graph`
2. run [uv run scripts/grpc_script.py](scripts/grpc_script.py) to execute the BFS on the graph.
 This script will look for the last commit in the `DEFAULT_BRANCH` for the chosen `KERNEL_TREE`. Defaults to the master in the mainline kernel. It is also possible to pre-load commits manually.
Must set the `GRAPH_GRPC_SERVER` and `INITIAL_NODE`, if non-default port or commit would be used.
3. run the [uv run scripts/enrich_from_git.py](scripts/enrich_from_git.py) script, pointing to the mainline branch path. This will load data that is unavailable in the graph. Tags can be loaded from the previous step, or loaded here if `LOAD_TAGS_FROM_REPO` is set.
 Example: `KERNEL_PATH=/media/research/linux uv run scripts/enrich_from_git.py`
4. run the [scripts/get_official_kernel_maintainers.py](scripts/get_official_kernel_maintainers.py) to read the contents of the maintainers file in all its changes. This step is independent from others, besides step 5.
  Example: `KERNEL_PATH=/media/research/linux uv run scripts/get_official_kernel_maintainers.py`
5. run the [scripts/stitch_data_into_final_payload.py] to get the daily output (with some calculation) and with all files in a single v

### Running application

Run either `podman-compose -f dev-compose.yaml up` for development or `podman-compose up` for production build

### Configuration

The API reads its configuration from environment variables (both compose
stacks and the Helm chart set them for you):

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_DIR` | `<repo>/data` | Data root; each module reads `<DATA_DIR>/<module>` |
| `DEBUG` | `false` | Flask debug mode; anything but `false` enables it |
| `HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in the dev container) |
| `PORT` | `5000` | Bind port |
| `CORS_ALLOWED_ORIGINS` | empty | Comma-separated browser origins allowed to call the API |
| `KERNEL_CACHE_WARMUP` | `true` | Pre-compute the dashboard's window sizes at startup; anything but `false` enables it |

`/api/commits` is backed by an in-memory cache keyed by window size, so the
expensive rolling-window calculation runs at most once per size per process.
With `KERNEL_CACHE_WARMUP` enabled (the default) the sizes the dashboard offers
(`1, 5, 14, 30, 60, 120, 365` days) are computed at startup and the first
request for each is instant. Set it to `false` to skip that warm-up: the same
windows are then computed on their first request. Other window sizes are
computed and cached on demand either way. The cache is process-local, so a
restart recomputes it from the data files.

## Kubernetes (Helm)

The production stack is also deployable to Kubernetes with the chart in
[`chart/`](chart). It mirrors `compose.yaml`: an `api` Deployment (backend +
the static frontend in the same image), an `nginx` Deployment that copies the
static files out of the api image with an initContainer, and an optional
generic `tunnel` sidecar as an alternative to an Ingress. See
[`chart/README.md`](chart/README.md) for the full values reference.

```bash
make image-build REGISTRY=ghcr.io/linux-duks IMAGE_TAG=latest
make image-push  REGISTRY=ghcr.io/linux-duks IMAGE_TAG=latest
make chart-install NAMESPACE=duks
make data-sync     NAMESPACE=duks   # copy ./data into the api pod's volume
```

The dataset is provided as a volume: a PVC created by the chart (default) or an
existing NFS export (`persistence.type: nfs`). DUKS is exposed either through an
Ingress (`ingress.enabled`) or through the tunnel sidecar (`tunnel.enabled`,
where you supply the image, command/args and env vars — the chart stays provider
agnostic); both are off by default.

| Target | Description |
|--------|-------------|
| `make image-build` | Build the production image (`server/Containerfile.prod`) |
| `make image-push` | Push it to `REGISTRY/IMAGE_NAME:IMAGE_TAG` |
| `make image-publish` | Both of the above |
| `make chart-lint` | `helm lint chart/` |
| `make chart-template` | Render the chart locally |
| `make chart-install` | `helm upgrade --install` into `NAMESPACE` |
| `make chart-uninstall` | Remove the release |
| `make chart-package` | Produce a `.tgz` of the chart |
| `make data-sync` | Copy `./data` into the running api pod's volume |

`make help` lists every target.

## Research

Papers related to this software:

- [Streamlining Analyses on the Linux Kernel with DUKS](https://doi.org/10.1109/VISSOFT67405.2025.00025)
- [DUKS: visualizações e análises unificadas para o Kernel Linux 🇧🇷](https://doi.org/10.5753/vem.2025.14637)

PASSOS, Rafael; PILONE, Arthur; TADOKORO, David; MEIRELLES, Paulo
