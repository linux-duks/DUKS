"""HTTP API for the Kernel statistics dashboard.

Serves the commit and tag data the dashboard frontend consumes. The data
frames themselves are built by :mod:`kernel.data_loader`; this module only
maps HTTP requests onto them.
"""

import os

from flask import Blueprint, current_app, jsonify, request

from kernel.data_loader import load_data, load_tags

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
    if "d" not in window_size:
        window_size = window_size + "d"

    current_app.logger.info("GET commits with window: %s", window_size)

    data = load_data(window_date_size=window_size)
    return jsonify(data.to_dict(as_series=False))


@bp.route("/api/tags", methods=["GET"])
def get_tags():
    """Endpoint to serve tag data."""
    return jsonify(load_tags().to_dicts())
