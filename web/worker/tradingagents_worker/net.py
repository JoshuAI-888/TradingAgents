"""HTTPS helper: use certifi's CA bundle when present (macOS python.org builds
ship without system certs); fall back to the default context elsewhere."""

from __future__ import annotations

import ssl
from urllib import request as _rq


def urlopen(req, timeout: int = 20):
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        return _rq.urlopen(req, timeout=timeout, context=ctx)
    except ImportError:
        return _rq.urlopen(req, timeout=timeout)
