"""Strict identity for private research data; no Phase 0 owner fallback."""
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from urllib import request, error

from fastapi import Header, HTTPException
from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db


@dataclass(frozen=True)
class ResearchOwner:
    id: str


def _auth_user(token: str) -> dict:
    req = request.Request(SETTINGS.supabase_url.rstrip('/') + '/auth/v1/user', headers={
        'apikey': SETTINGS.supabase_service_key, 'Authorization': 'Bearer ' + token,
    })
    try:
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise HTTPException(401, 'Sign in again to access private research.') from None
        raise HTTPException(503, 'Authentication is temporarily unavailable.') from None
    except (OSError, ValueError):
        raise HTTPException(503, 'Authentication is temporarily unavailable.') from None


def _session_active(owner: str, session: str) -> bool:
    try:
        # Service-only RPC; no auth.sessions data is exposed to the browser.
        return Db()._call('POST', 'rpc/research_session_active',
                          body={'p_owner': owner, 'p_session': session}) is True
    except RuntimeError:
        raise HTTPException(503, 'Research session validation is temporarily unavailable.') from None


def require_research_owner(authorization: str = Header(default='')) -> ResearchOwner:
    if not isinstance(authorization, str) or len(authorization) > 8192:
        raise HTTPException(401, 'Sign in to access private research.')
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise HTTPException(401, 'Sign in to access private research.')
    if not SETTINGS.supabase_url or not SETTINGS.supabase_service_key:
        raise HTTPException(503, 'Research authentication is not configured.')
    token = parts[1]
    user = _auth_user(token)  # Verify with the issuer BEFORE reading any token claims.
    try:
        owner = str(uuid.UUID(user['id']))
        if user.get('is_anonymous') is not False:
            raise ValueError('Unverified account type')
        encoded = token.split('.')
        if len(encoded) != 3:
            raise ValueError('Missing session claims')
        claims = json.loads(base64.urlsafe_b64decode(encoded[1] + '=' * (-len(encoded[1]) % 4)))
        session = str(uuid.UUID(claims['session_id']))
        if claims.get('sub') != owner:
            raise ValueError('Identity mismatch')
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, 'Sign in again to access private research.') from None
    if not _session_active(owner, session):
        raise HTTPException(401, 'Your research session ended. Sign in again.')
    return ResearchOwner(owner)
