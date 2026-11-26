"""In-memory cache for the expensive commit calculations.

:func:`kernel.data_loader.load_data` recomputes a set of rolling-window counts
over the kernel's whole history on every call (several seconds for the largest
window), which is too heavy to serve live. This module keeps the JSON-ready
payload per window size so each distinct window is computed at most once per
process.

The cache is process-local: restarting the process refreshes it. With a
forking server that preloads the app (``gunicorn --preload``) the warm-up runs
once in the master and the workers inherit the filled cache; without preload
every worker warms its own copy.

Bounded, like the treemap response cache in :mod:`knowledge_map.api`: an entry
is ~0.6 MB (the 365-day payload) and the window comes from the query string, so
an unbounded map would be a memory leak in slow motion. Insertion order makes
evicting the least recently used entry a one-liner.
"""

import logging
import os
import threading

from kernel.data_loader import load_data

logger = logging.getLogger(__name__)

# Window sizes the dashboard offers. Warming these at startup makes the first
# click on any of them fast.
KNOWN_WINDOW_SIZES = ("1", "5", "14", "30", "60", "120", "365")

CACHE_MAX = 16

# Same convention as DEBUG in app.py: anything but the literal "false" keeps
# the startup warm-up enabled.
WARMUP_ENABLED = os.getenv("KERNEL_CACHE_WARMUP", "true") != "false"

# window key -> JSON-ready payload, oldest (least recently used) first
_cache = {}

# Requests run on threads, so every touch of _cache goes through this lock.
_cache_lock = threading.Lock()

# One lock per window key, so a multi-second build only blocks requests for
# the same window instead of every dashboard window. Entries are dropped once
# the build finishes; a thread that already holds the lock object still waits
# on it correctly, and by then the payload is in _cache.
_compute_locks = {}


def normalize_window_size(window_size=None):
    """Canonicalize a requested window to the ``<n>d`` form Polars expects."""
    if not window_size:
        return "1d"
    window_size = str(window_size)
    if "d" not in window_size:
        window_size = window_size + "d"
    return window_size


def _cache_get(key):
    """Cached payload for ``key``, marking it as most recently used."""
    with _cache_lock:
        payload = _cache.get(key)
        if payload is None:
            return None
        _cache.pop(key)
        _cache[key] = payload
        return payload


def _cache_put(key, payload):
    with _cache_lock:
        _cache.pop(key, None)  # re-insert at the newest end
        _cache[key] = payload
        while len(_cache) > CACHE_MAX:
            _cache.pop(next(iter(_cache)))


def _compute_lock(key):
    with _cache_lock:
        return _compute_locks.setdefault(key, threading.Lock())


def _release_compute_lock(key, lock):
    with _cache_lock:
        if _compute_locks.get(key) is lock:
            _compute_locks.pop(key, None)


def _compute(window_size):
    data = load_data(window_date_size=window_size)
    return data.to_dict(as_series=False)


def get_commits_payload(window_size="1d"):
    """Return the commit payload for ``window_size``, computing it once.

    Unknown sizes are cached too, so every distinct window pays the expensive
    calculation at most once per process.
    """
    key = normalize_window_size(window_size)
    payload = _cache_get(key)
    if payload is not None:
        return payload

    lock = _compute_lock(key)
    with lock:
        try:
            # Double-checked: a concurrent request may have filled the entry
            # while this one waited for the lock.
            payload = _cache_get(key)
            if payload is None:
                payload = _compute(key)
                _cache_put(key, payload)
        finally:
            _release_compute_lock(key, lock)
    return payload


def warm_cache(window_sizes=KNOWN_WINDOW_SIZES):
    """Pre-compute and cache every window size in ``window_sizes``."""
    for window_size in window_sizes:
        get_commits_payload(window_size)


def warm_cache_if_enabled():
    """Warm the known window sizes unless KERNEL_CACHE_WARMUP disables it.

    Best effort: a failure (missing or unreadable data) is logged and the
    process keeps starting. The affected window is retried on first request,
    which surfaces the usual error response.
    """
    if not WARMUP_ENABLED:
        logger.info("KERNEL_CACHE_WARMUP is off; skipping commits cache warm-up")
        return

    logger.info("Warming commits cache for windows: %s", ", ".join(KNOWN_WINDOW_SIZES))
    try:
        warm_cache()
    except Exception:  # noqa: BLE001 - startup must survive bad/missing data
        logger.warning(
            "Commits cache warm-up failed; windows will be computed on demand",
            exc_info=True,
        )
        return
    logger.info("Commits cache warm-up complete")
