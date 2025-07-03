from flask import Flask, request, jsonify, make_response
from data_loader import load_pre_calculated_frame, load_tags

import orjson
import os
import logging

DEBUG = os.getenv("DEBUG", "false")
level = logging.INFO
if DEBUG != "false":
    level = logging.DEBUG

app = Flask(__name__)


def _build_cors_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response


@app.route("/api/commits", methods=["GET"])
def get_commits():
    """
    Endpoint to serve the Git commit data.
    """
    if request.method == "OPTIONS":  # CORS preflight
        return _build_cors_preflight_response()
    elif request.method == "GET":
        window_size = request.args.get("window_size", "1")

        app.logger.info("GET commits with window: %s", window_size)

        data = load_pre_calculated_frame(window_date_size=window_size)
        response = jsonify(data)
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
    else:
        raise RuntimeError(
            "Couldn't address request with HTTP method {}".format(request.method)
        )


@app.route("/api/tags", methods=["GET"])
def get_tags():
    """
    Endpoint to serve tag data.
    """
    if request.method == "OPTIONS":  # CORS preflight
        return _build_cors_preflight_response()
    elif request.method == "GET":
        data = load_tags()
        response = jsonify(data.to_dicts())
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
    else:
        raise RuntimeError(
            "Couldn't address request with HTTP method {}".format(request.method)
        )


@app.route("/")
def home():
    return app.send_static_file("index.html")


class ORJSONDecoder:
    def __init__(self, **kwargs):
        # eventually take into consideration when deserializing
        self.options = kwargs

    def decode(self, obj):
        return orjson.loads(obj)


class ORJSONEncoder:
    def __init__(self, **kwargs):
        # eventually take into consideration when serializing
        self.options = kwargs

    def encode(self, obj):
        # decode back to str, as orjson returns bytes
        return orjson.dumps(obj).decode("utf-8")


if __name__ == "__main__":
    app.json_encoder = ORJSONEncoder
    app.json_decoder = ORJSONDecoder
    # Use 0.0.0.0 to make the server accessible from outside the container
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)
