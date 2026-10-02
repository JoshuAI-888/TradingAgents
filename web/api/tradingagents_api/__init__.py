"""Portal API package.

The API reuses the worker layer (config/db). tradingagents_worker ships as a
sibling directory, not a pip package — make it importable when this package is
loaded from web/api (Render startCommand cwd) or any other layout.
"""

import os
import sys

_worker_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "worker")
)
if os.path.isdir(os.path.join(_worker_dir, "tradingagents_worker")) and _worker_dir not in sys.path:
    sys.path.insert(0, _worker_dir)
