"""Single place that knows where a module's data files live.

Every module keeps its data in its own folder under the data root::

    data/
        kernel/           -> Kernel dashboard exports (parquet/CSV)
        knowledge_map/    -> treemap CSVs, one per repository

Modules never hard-code data paths; they ask this module for their folder.
The root defaults to the repository's ``data/`` directory (``<server>/../data``)
and can be overridden with the ``DATA_DIR`` environment variable -- the
container mounts the volume at ``/data``, for instance.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# `or` rather than a default argument so an empty DATA_DIR also falls back.
DATA_ROOT = os.path.abspath(
    os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "..", "data")
)


def module_data_dir(module: str) -> str:
    """Absolute path to ``module``'s data folder."""
    return os.path.join(DATA_ROOT, module)


def module_data_file(module: str, *parts: str) -> str:
    """Absolute path to a file inside ``module``'s data folder."""
    return os.path.join(module_data_dir(module), *parts)
