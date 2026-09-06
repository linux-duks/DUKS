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
├── data              -> where the data files should be stored
│   └── knowledge-map -> per-repository node CSVs for the treemap (see below)
├── nginx             -> configurations for nginx (for production)
├── scripts           -> scripts used to generate the dataset
└── server            -> backend source code
    ├── knowledge_map_api.py -> treemap API blueprint (/api/knowledge-map/*)
    └── static              -> static Frontend files
        └── knowledge-map   -> the Knowledge Distribution Treemap page (/knowledge-map)
```

## Dashboards

- **Kernel Statistics Dashboard** (`/dashboard`) — contributor and lines-of-code
  time series over the kernel's history.
- **Knowledge Distribution Treemap** (`/knowledge-map`) — a nested treemap of a
  codebase where each rectangle's area is how much code a file or folder holds
  and its colour is its Pony Factor
  (how few authors wrote most of that code). It reads per-repository CSVs from
  `data/knowledge-map/*.csv`; each row is one node with at least the columns
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
Run scripts from the project root directory (as it will create a `./data/` folder relative to the scripts).
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

## Research

Papers related to this software:

- [Streamlining Analyses on the Linux Kernel with DUKS](https://doi.org/10.1109/VISSOFT67405.2025.00025)
- [DUKS: visualizações e análises unificadas para o Kernel Linux 🇧🇷](https://doi.org/10.5753/vem.2025.14637)

PASSOS, Rafael; PILONE, Arthur; TADOKORO, David; MEIRELLES, Paulo
