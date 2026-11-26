"""Shared Flask application shell.

This is the only piece of server infrastructure that knows about every module.
Each module exposes its own blueprint (and resolves its own data folder via
``data_dirs``); this file just wires them into one app and serves the static
pages.
"""

import os

from flask import Flask

from kernel.api import bp as kernel_bp
from knowledge_map.api import bp as knowledge_map_bp

# DEBUG is a string in the environment; treat anything but "false" as enabled.
DEBUG = os.getenv("DEBUG", "false") != "false"
# Loopback by default; containers opt in to the wildcard bind through HOST so
# the published port can reach the app.
HOST = os.getenv("HOST", "127.0.0.1")


def _port_from_env():
    """PORT as an int, failing loudly instead of silently using a default."""
    raw = os.getenv("PORT", "5000")
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"PORT must be an integer, got {raw!r}") from exc


PORT = _port_from_env()

app = Flask(__name__)
app.register_blueprint(kernel_bp)
app.register_blueprint(knowledge_map_bp)


@app.route("/")
def home():
    return app.send_static_file("index.html")


@app.route("/dashboard")
def dashboard():
    return app.send_static_file("dashboard.html")


@app.route("/knowledge-map")
@app.route("/knowledge-map/")
def knowledge_map():
    return app.send_static_file("knowledge-map/index.html")


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
