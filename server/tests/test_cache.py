"""Tests for the in-memory commits cache (``kernel.cache``)."""

import pytest
from flask import Flask

from kernel import cache
from kernel.api import bp as kernel_bp


class FakeFrame:
    """Stand-in for the Polars frame returned by ``load_data``."""

    def __init__(self, window_size):
        self.window_size = window_size

    def to_dict(self, *, as_series=False):
        return {"window_size": [self.window_size]}


@pytest.fixture(autouse=True)
def clear_cache():
    """Each test starts and ends with an empty cache."""
    cache._cache.clear()
    yield
    cache._cache.clear()


@pytest.fixture
def fake_load_data(monkeypatch):
    """Patch ``load_data`` and record every window it was called with."""
    calls = []

    def load_data(window_date_size=None):
        calls.append(window_date_size)
        return FakeFrame(window_date_size)

    monkeypatch.setattr(cache, "load_data", load_data)
    return calls


def test_normalize_window_size():
    assert cache.normalize_window_size("365") == "365d"
    assert cache.normalize_window_size("14d") == "14d"
    assert cache.normalize_window_size("1") == "1d"
    assert cache.normalize_window_size("") == "1d"
    assert cache.normalize_window_size(None) == "1d"


def test_get_commits_payload_computes_once(fake_load_data):
    first = cache.get_commits_payload("14")
    second = cache.get_commits_payload("14d")

    assert first == {"window_size": ["14d"]}
    assert second is first
    assert fake_load_data == ["14d"]


def test_get_commits_payload_caches_unknown_size(fake_load_data):
    assert cache.get_commits_payload("7") == {"window_size": ["7d"]}
    assert cache.get_commits_payload("7d") is cache.get_commits_payload("7")
    assert fake_load_data == ["7d"]


def test_cache_holds_every_known_window():
    # Warm-up must not evict its own first entries.
    max_entries = cache.CACHE_MAX
    assert max_entries >= len(cache.KNOWN_WINDOW_SIZES)


def test_warm_cache_fills_known_windows(fake_load_data):
    cache.warm_cache()

    expected = [f"{size}d" for size in cache.KNOWN_WINDOW_SIZES]
    assert sorted(cache._cache) == sorted(expected)
    assert sorted(fake_load_data) == sorted(expected)


def test_cache_evicts_least_recently_used(fake_load_data, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_MAX", 2)

    cache.get_commits_payload("1")  # oldest
    cache.get_commits_payload("5")
    cache.get_commits_payload("1")  # touch, so "5d" becomes the oldest
    cache.get_commits_payload("14")  # evicts "5d"

    assert sorted(cache._cache) == ["14d", "1d"]


def test_compute_locks_are_released(fake_load_data):
    cache.get_commits_payload("14")

    assert cache._compute_locks == {}


def test_concurrent_requests_compute_once(fake_load_data):
    import threading

    results = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        results.append(cache.get_commits_payload("14"))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert fake_load_data == ["14d"]
    assert all(result == {"window_size": ["14d"]} for result in results)


def test_warm_cache_if_enabled_when_enabled(monkeypatch, fake_load_data):
    monkeypatch.setattr(cache, "WARMUP_ENABLED", True)

    cache.warm_cache_if_enabled()

    assert sorted(cache._cache) == sorted(
        f"{size}d" for size in cache.KNOWN_WINDOW_SIZES
    )


def test_warm_cache_if_enabled_when_disabled(monkeypatch, fake_load_data):
    monkeypatch.setattr(cache, "WARMUP_ENABLED", False)

    cache.warm_cache_if_enabled()

    assert cache._cache == {}
    assert fake_load_data == []


def test_warm_cache_if_enabled_survives_failure(monkeypatch):
    def failing_load_data(window_date_size=None):
        raise FileNotFoundError("missing parquet")

    monkeypatch.setattr(cache, "WARMUP_ENABLED", True)
    monkeypatch.setattr(cache, "load_data", failing_load_data)

    # Startup must not raise; the windows are retried on demand.
    cache.warm_cache_if_enabled()

    assert cache._cache == {}


def test_route_serves_cached_payload(monkeypatch, fake_load_data):
    monkeypatch.setattr(cache, "WARMUP_ENABLED", False)
    app = Flask(__name__)
    app.register_blueprint(kernel_bp)
    client = app.test_client()

    first = client.get("/api/commits?window_size=14")
    second = client.get("/api/commits?window_size=14")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == {"window_size": ["14d"]}
    assert second.get_json() == first.get_json()
    assert fake_load_data == ["14d"]
