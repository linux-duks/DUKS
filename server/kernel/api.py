"""HTTP API for the Kernel statistics dashboard.

Serves the commit and tag data the dashboard frontend consumes. The data
frames themselves are built by :mod:`kernel.data_loader`; this module only
maps HTTP requests onto them. The heavy commit calculation is served from the
in-memory cache in :mod:`kernel.cache`.
"""

import os

from flask import Blueprint, current_app, jsonify, request

from kernel.cache import get_commits_payload
from kernel.data_loader import load_tags

bp = Blueprint("kernel", __name__)

# Browser origins allowed to call the stats API. Empty by default: the
# dashboard is served from the same origin as the API, which needs no CORS
# header. A deployment with a separate frontend host opts in with a
# comma-separated allowlist (CORS_ALLOWED_ORIGINS=https://example.org).
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}


@bp.after_request
def add_cors_headers(response):
    """Echo CORS headers back for an explicitly allowed Origin.

    Runs for the automatic OPTIONS preflight too, so a configured origin gets
    both the preflight and the real response covered.
    """
    origin = request.headers.get("Origin")
    if origin and origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers.add("Vary", "Origin")
    return response


@bp.route("/api/commits", methods=["GET"])
def get_commits():
    """Endpoint to serve the Git commit data."""
    window_size = request.args.get("window_size", "1d")

    current_app.logger.info("GET commits with window: %s", window_size)

    # Served from the in-memory cache: the rolling-window calculation runs at
    # most once per window size per process (warmed at startup by default).
    return jsonify(get_commits_payload(window_size))


@bp.route("/api/tags", methods=["GET"])
def get_tags():
    """Endpoint to serve tag data."""
    return jsonify(load_tags().to_dicts())
