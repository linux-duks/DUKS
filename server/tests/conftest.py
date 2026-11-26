"""Test bootstrap: make the ``server`` package root importable.

The application modules are imported as top-level names (``kernel.cache``,
``data_dirs``, ...), matching how gunicorn runs ``app:app`` from ``server/``.
"""

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
