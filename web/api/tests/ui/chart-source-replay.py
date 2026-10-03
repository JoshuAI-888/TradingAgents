"""Offline current-chart replay of captured public quote/candle responses.

Usage: python chart-source-replay.py CODE QUOTE_JSON CANDLES_JSON [PORT]
Other API data is unavailable. No network calls, data mutation or database.
"""

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

symbol = sys.argv[1]
quote = json.loads(Path(sys.argv[2]).read_text())
candles = json.loads(Path(sys.argv[3]).read_text())
if quote.get("code") != symbol or quote.get("available") is not True or not candles.get("bars"):
    raise ValueError("Replay requires a matching available quote and nonempty candle response")


class Replay(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, directory=str(Path(__file__).resolve().parents[2] / "static"), **kwargs
        )

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        data = {"available": False, "rows": [], "presets": []}
        if url.path == "/api/health":
            data = {"status": "ok"}
        elif url.path == "/api/meta":
            data = {"spend": {}}
        elif url.path == f"/api/stock/{symbol}/quote":
            data = quote
        elif url.path == f"/api/stock/{symbol}/candles" and parse_qs(url.query).get("range") == [
            candles.get("range")
        ]:
            data = candles
        body = json.dumps(data, allow_nan=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


port = int(sys.argv[4]) if len(sys.argv) > 4 else 8914
print(
    f"Offline captured {symbol} chart: {len(candles['bars'])} bars at localhost:{port}", flush=True
)
ThreadingHTTPServer(("127.0.0.1", port), Replay).serve_forever()
