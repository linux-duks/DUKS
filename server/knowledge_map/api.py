"""Knowledge Distribution Treemap — API blueprint.

Serves the nested treemap of per-file/per-directory knowledge concentration
("Pony Factor") for a selectable open-source codebase. Two endpoints:

    GET /api/knowledge-map/repos          -> the datasets the selector can offer
    GET /api/knowledge-map/tree?repo=...  -> the nested tree for one dataset

Ported from the standalone Flask app in https://github.com/rodrigo271113/tcc-dev
(`src/app.py`). The dataframe work was rewritten from pandas to polars to keep
DUKS on a single dataframe stack; the tree-building, the response cache and the
path-traversal guard are unchanged in spirit.
"""

import io
import os
import threading

import orjson
import polars as pl
from flask import Blueprint, Response, request

from data_dirs import module_data_dir

bp = Blueprint("knowledge_map", __name__)

# Each module owns a folder under the shared data root; see data_dirs.py.
DATA_DIR = module_data_dir("knowledge_map")
DEFAULT_REPO = "tokenFilesFull"

# Not a repository: an ~860MB aggregate of every project, which would only
# stall the server if someone picked it from the dropdown.
EXCLUDED_CSVS = {"_all_projects.csv"}

# Columns the tree builder actually needs. Present in both CSV families, so
# they double as the signal for "did we split this header on the right char?".
REQUIRED_COLUMNS = ("identifier", "pony_factor", "node_len_lines", "node_name")

# The two CSV families use different separators: the token dumps are plain
# comma-separated, while the per-project exports use an INTERPUNCT (U+00B7) --
# a character that essentially never shows up in real path/file content.
# Detection looks at the header rather than trying to parse: polars (like
# pandas' C parser) happily reads an interpunct file with sep=',' and just
# yields one fat column, so a failed parse is not something an exception
# reports.
CSV_SEPARATORS = ("·", ",")
INTERPUNCT_UTF8 = b"\xc2\xb7"        # U+00B7 as encoded in the file
# polars' separator must be a single byte, so an interpunct file is rewritten
# to this delimiter first. ASCII Unit Separator: control char, never valid in
# a path or file name, so it cannot collide with real content.
SAFE_SEP = b"\x1f"

# Built trees, keyed by csv path -> {"mtime", "body"}; a slot is rebuilt only
# when that file changed. `body` is the finished JSON bytes: serialising the
# tree is ~0.3s on the kernel dataset, so memoising only the dict would leave
# that cost on every request.
#
# Bounded because an entry is several MB (~8.8MB for the kernel, more for the
# largest projects): an unbounded map over 80+ repos would be a memory leak in
# slow motion. Insertion order makes eviction of the oldest entry a one-liner.
_tree_cache = {}
TREE_CACHE_MAX = 4

# Requests run on threads, so every touch of _tree_cache goes through this
# lock. Individually a dict get/set is atomic under the GIL, but the eviction
# below is not (read the oldest key, then pop it -- two steps). The build
# itself deliberately runs OUTSIDE the lock: holding it across a multi-second
# build would make one slow repository block every other one.
_cache_lock = threading.Lock()


def cache_get(csv_path, mtime):
    """Cached JSON bytes for this CSV, or None if absent/stale."""
    with _cache_lock:
        entry = _tree_cache.get(csv_path)
        if entry is None:
            return None
        if entry["mtime"] != mtime:
            _tree_cache.pop(csv_path, None)
            return None
        # Touch on read, so "oldest" below means least recently *used*.
        _tree_cache.pop(csv_path)
        _tree_cache[csv_path] = entry
        return entry["body"]


def cache_put(csv_path, mtime, body):
    with _cache_lock:
        _tree_cache.pop(csv_path, None)      # re-insert at the newest end
        _tree_cache[csv_path] = {"mtime": mtime, "body": body}
        while len(_tree_cache) > TREE_CACHE_MAX:
            _tree_cache.pop(next(iter(_tree_cache)))


def _json_response(body, status=200):
    return Response(body, status=status, mimetype="application/json")


# ---------------------------------------------------------------------------
# Repository listing / path resolution
# ---------------------------------------------------------------------------

def list_repos():
    """Names (basename minus '.csv') of every repository CSV in DATA_DIR."""
    try:
        entries = os.listdir(DATA_DIR)
    except OSError:
        return []
    return sorted(
        (f[:-4] for f in entries
         if f.endswith(".csv") and f not in EXCLUDED_CSVS
         and os.path.isfile(os.path.join(DATA_DIR, f))),
        key=str.lower,
    )


def resolve_repo_path(repo):
    """Map a user-supplied repo name to its CSV path, or None if not allowed.

    The name arrives straight from the query string and ends up in a file
    path, so it is never concatenated in blind: it must match -- exactly, by
    string equality -- one of the names the directory scan actually found.
    Anything with a path separator, a '..' segment, or an absolute/drive-ish
    shape is rejected up front as well.
    """
    if not repo:
        return os.path.join(DATA_DIR, DEFAULT_REPO + ".csv")
    if os.path.sep in repo or (os.path.altsep and os.path.altsep in repo):
        return None
    if "/" in repo or "\\" in repo or ".." in repo or repo.startswith("."):
        return None
    if os.path.isabs(repo) or os.path.basename(repo) != repo:
        return None
    if repo not in list_repos():
        return None
    path = os.path.join(DATA_DIR, repo + ".csv")
    # Belt and braces: the joined path must still live directly in DATA_DIR.
    # (abspath, not realpath -- data files are legitimately symlinks here.)
    if os.path.dirname(os.path.abspath(path)) != DATA_DIR:
        return None
    return path


# The `node_len_lines` column does NOT hold the same unit in every dataset, so
# the label has to follow the repository rather than the column name: the token
# dumps (tokenFilesFull) are token counts, the per-project exports are line
# counts.
TOKEN_REPOS = {"tokenFilesFull"}


def repo_unit(repo):
    """The unit `node_len_lines` is measured in for this repository."""
    return "tokens" if repo in TOKEN_REPOS else "lines"


def format_size(size, unit):
    """Render a size as a grouped string, e.g. 12345 -> '12,345 tokens'."""
    try:
        return f"{int(size):,} {unit}"
    except (TypeError, ValueError):
        return f"{size} {unit}"


# ---------------------------------------------------------------------------
# CSV reading + tree building
# ---------------------------------------------------------------------------

def read_repo_csv(csv_path):
    """Read a node CSV as an all-string frame, picking the separator from the
    header. Every column comes back as Utf8 so the numeric coercion below is
    explicit and dataset-independent."""
    with open(csv_path, "rb") as fh:
        raw = fh.read()

    header = raw.split(b"\n", 1)[0].decode("utf-8", "replace").rstrip("\r")

    for sep in CSV_SEPARATORS:
        fields = [f.strip() for f in header.split(sep)]
        if all(col in fields for col in REQUIRED_COLUMNS):
            if sep == "·":
                raw = raw.replace(INTERPUNCT_UTF8, SAFE_SEP)
                delimiter = SAFE_SEP.decode("ascii")
            else:
                delimiter = ","
            return pl.read_csv(
                io.BytesIO(raw),
                separator=delimiter,
                infer_schema=False,         # read every column as Utf8
                truncate_ragged_lines=True,
            )

    raise ValueError(
        f"unrecognised CSV header in {os.path.basename(csv_path)}: "
        f"expected columns {', '.join(REQUIRED_COLUMNS)} separated by "
        f"one of {CSV_SEPARATORS}"
    )


def _numeric_column(df, column, fallback):
    """Vectorised stand-in for a per-row `float(row.get(column, default))`.

    Missing column -> the whole column is null. A cell that is not a number at
    all falls back to `fallback`; a genuinely empty cell stays null (which
    serialises to JSON null, exactly like float(nan) did before).
    """
    if column not in df.columns:
        return pl.Series(column, [None] * df.height, dtype=pl.Float64)
    raw = pl.col(column)
    num = raw.cast(pl.Float64, strict=False)
    expr = (
        pl.when(num.is_null() & raw.is_not_null() & (raw.str.strip_chars() != ""))
        .then(pl.lit(float(fallback)))
        .otherwise(num)
        .alias(column)
    )
    return df.select(expr).get_column(column)


def _color_column(tf):
    """Bucket a whole column of Pony Factors into colours at once.

    Same thresholds (and same order) as the legend in index.html -- keep both
    in sync. A null Pony Factor compares False against every bound and lands on
    grey, exactly like the old NaN fallback did.
    """
    col = pl.col("tf")
    expr = (
        pl.when(col <= 1).then(pl.lit("#ef4444"))   # Red (High Risk)
        .when(col <= 2).then(pl.lit("#eab308"))     # Yellow
        .when(col <= 5).then(pl.lit("#22c55e"))     # Green
        .otherwise(pl.lit("#94a3b8"))               # Grey (Low Risk)
        .alias("color")
    )
    return pl.DataFrame({"tf": tf}).select(expr).get_column("color")


def build_tree_body(csv_path, unit="lines"):
    """Read a node CSV and return the nested tree as JSON bytes."""
    df = read_repo_csv(csv_path)

    root = {
        "name": "Project Root",
        "children": [],
        "path": "",
        "color": "#334155",
        # Travels with the tree so the breadcrumb and the tooltip/search
        # fallbacks label sizes the same way the server did.
        "unit": unit,
    }

    if "identifier" in df.columns:
        identifier = df.get_column("identifier").fill_null("")
    else:
        identifier = pl.Series("identifier", [""] * df.height, dtype=pl.Utf8)
    df = df.with_columns(identifier.alias("identifier"))

    # The root row (empty identifier) contributes its metadata to `root` only.
    is_root_row = df.get_column("identifier") == ""
    if is_root_row.any():
        root_rows = df.filter(is_root_row)
        if "pony_factor" in root_rows.columns and root_rows.height:
            try:
                root["tf"] = float(root_rows.get_column("pony_factor")[-1])
            except (TypeError, ValueError):
                pass
        df = df.filter(~is_root_row)

    # One node per path: a repeated identifier keeps its LAST row (the frontend
    # keys its data-join on path, so a duplicate would otherwise clobber).
    if df.height:
        df = df.unique(subset="identifier", keep="last", maintain_order=True)

    identifier = df.get_column("identifier")
    if "node_name" in df.columns:
        node_name = df.get_column("node_name").fill_null("")
    else:
        node_name = identifier.str.split("/").list.last().fill_null("")

    tf = _numeric_column(df, "pony_factor", 10)
    size = _numeric_column(df, "node_len_lines", 1)
    colors = _color_column(tf)

    paths = identifier.to_list()
    names = node_name.to_list()
    tfs = tf.to_list()
    sizes = size.to_list()
    color_list = colors.to_list()
    actual_sizes = [format_size(s, unit) for s in sizes]

    nodes = [
        {
            "name": name,
            "path": path,
            "color": color,
            "tf": node_tf,
            "value": node_size,
            "actual_size": actual_size,
        }
        for name, path, color, node_tf, node_size, actual_size
        in zip(names, paths, color_list, tfs, sizes, actual_sizes)
    ]

    # parent id = identifier minus the trailing "/<node_name>" segment. Sliced
    # by node_name's length rather than split on "/": node_name is what makes
    # this rule exact, and re-deriving the segment from the string produced
    # phantom duplicate directories in an earlier version.
    parent_ids = [path[: max(0, len(path) - len(name) - 1)]
                  for path, name in zip(paths, names)]

    by_path = dict(zip(paths, nodes))
    by_path[""] = root

    # Attach each node to its parent (unknown parent -> root). A node only
    # grows a "children" list when it actually gets one, so leaves never carry
    # an empty array; and the first child is where a node is revealed to be a
    # directory, so that is where its (redundant, subtree-total) "value" goes
    # away -- D3's .sum() must derive internal-node area from leaves alone.
    for parent_id, node in zip(parent_ids, nodes):
        parent = by_path.get(parent_id, root)
        children = parent.get("children")
        if children is None:
            parent.pop("value", None)
            children = parent["children"] = []
        children.append(node)

    if not root["children"]:
        del root["children"]

    return orjson.dumps(root)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/api/knowledge-map/repos")
def get_repos():
    """The repositories the selector can offer, plus the default."""
    return _json_response(
        orjson.dumps({"repos": list_repos(), "default": DEFAULT_REPO})
    )


@bp.route("/api/knowledge-map/tree")
def get_tree():
    repo = request.args.get("repo", "", type=str).strip()
    csv_path = resolve_repo_path(repo)
    if csv_path is None:
        return _json_response(
            orjson.dumps({"error": f"unknown repository: {repo!r}"}), status=400
        )
    if not os.path.isfile(csv_path):
        return _json_response(
            orjson.dumps({"error": f"no data file for repository: {repo!r}"}),
            status=404,
        )

    mtime = os.path.getmtime(csv_path)
    cached = cache_get(csv_path, mtime)
    if cached is not None:
        return _json_response(cached)

    try:
        body = build_tree_body(csv_path, repo_unit(repo or DEFAULT_REPO))
    except Exception as exc:  # noqa: BLE001 -- a bad CSV is data, not a crash
        from flask import current_app

        current_app.logger.exception("failed to build tree for %s", csv_path)
        return _json_response(
            orjson.dumps(
                {"error": f"could not read repository "
                          f"{repo or DEFAULT_REPO!r}: {exc}"}
            ),
            status=500,
        )

    cache_put(csv_path, mtime, body)
    return _json_response(body)
