"""Serve the current static Desk with a recorded public US screener cohort.

For table performance only. Other routes use offline preview fixtures; do not
use this server to qualify ticker detail, presets, market coverage or freshness.
No network, refresh, database writes or generation fabrication.
Usage: python cohort-replay.py RESPONSE_JSON [PORT]
"""

import importlib.util
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

spec = importlib.util.spec_from_file_location("preview", Path(__file__).with_name("preview.py"))
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
payload = json.loads(Path(sys.argv[1]).read_text())
rows = payload.get("rows")
if not isinstance(rows, list) or not rows or len(rows) != payload.get("matched"):
    raise ValueError("Replay requires a complete nonempty captured matching cohort")
codes = [r.get("code") for r in rows]
if len(set(codes)) != len(codes) or any(
    not isinstance(c, str) or not c.startswith("US.") for c in codes
):
    raise ValueError("Replay requires unique US canonical identities")


class Replay(preview.Handler):
    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/api/screener":
            market = parse_qs(path.query).get("market", ["US"])[0]
            data = (
                payload
                if market == "US"
                else {
                    "available": False,
                    "rows": [],
                    "matched": 0,
                    "server_fallback_reason": "No recorded HK cohort in this offline replay.",
                }
            )
            body = json.dumps(data, allow_nan=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.path == "/api/screener/execute":
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"Preset executions are not qualified by cohort replay."}')
        else:
            super().do_GET()


port = int(sys.argv[2]) if len(sys.argv) > 2 else 8911
print(f"Offline recorded US cohort replay: {len(rows)} rows at localhost:{port}", flush=True)
ThreadingHTTPServer(("127.0.0.1", port), Replay).serve_forever()
