"""Strict identity for private research data; no Phase 0 owner fallback."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from urllib import error, request

from fastapi import Header, HTTPException
from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db


@dataclass(frozen=True)
class ResearchOwner:
    id: str


def _auth_user(token: str) -> dict:
    req = request.Request(
        SETTINGS.supabase_url.rstrip("/") + "/auth/v1/user",
        headers={
            "apikey": SETTINGS.supabase_service_key,
            "Authorization": "Bearer " + token,
        },
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise HTTPException(401, "Sign in again to access private research.") from None
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    except (OSError, ValueError):
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None


def _session_active(owner: str, session: str) -> bool:
    try:
        # Service-only RPC; no auth.sessions data is exposed to the browser.
        return (
            Db()._call(
                "POST", "rpc/research_session_active", body={"p_owner": owner, "p_session": session}
            )
            is True
        )
    except RuntimeError:
        raise HTTPException(
            503, "Research session validation is temporarily unavailable."
        ) from None


def require_research_owner(authorization: str = Header(default="")) -> ResearchOwner:
    if not isinstance(authorization, str) or len(authorization) > 8192:
        raise HTTPException(401, "Sign in to access private research.")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Sign in to access private research.")
    if not SETTINGS.supabase_url or not SETTINGS.supabase_service_key:
        raise HTTPException(503, "Research authentication is not configured.")
    token = parts[1]
    user = _auth_user(token)  # Verify with the issuer BEFORE reading any token claims.
    try:
        owner = str(uuid.UUID(user["id"]))
        if user.get("is_anonymous") is not False:
            raise ValueError("Unverified account type")
        encoded = token.split(".")
        if len(encoded) != 3:
            raise ValueError("Missing session claims")
        claims = json.loads(base64.urlsafe_b64decode(encoded[1] + "=" * (-len(encoded[1]) % 4)))
        session = str(uuid.UUID(claims["session_id"]))
        if claims.get("sub") != owner:
            raise ValueError("Identity mismatch")
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "Sign in again to access private research.") from None
    if not _session_active(owner, session):
        raise HTTPException(401, "Your research session ended. Sign in again.")
    return ResearchOwner(owner)


# Same-origin Auth transport. No public database client key or service key leaves
# this process. The browser keeps its session in tab-scoped sessionStorage.
import time  # noqa: E402 - initialization must precede this import

from fastapi import APIRouter, Request  # noqa: E402 - initialization must precede this import
from starlette.concurrency import (  # noqa: E402 - initialization must precede this import
    run_in_threadpool,
)

router = APIRouter(prefix="/api/research/auth", tags=["Research sign in"])


def _auth_exchange(path: str, body: dict | None = None, token: str | None = None):
    if not SETTINGS.supabase_url or not SETTINGS.supabase_service_key:
        raise HTTPException(503, "Research authentication is not configured.")
    req = request.Request(
        SETTINGS.supabase_url.rstrip("/") + "/auth/v1/" + path,
        method="POST",
        data=json.dumps(body).encode() if body is not None else b"",
        headers={
            "apikey": SETTINGS.supabase_service_key,
            "Content-Type": "application/json",
            **({"Authorization": "Bearer " + token} if token else {}),
        },
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        if exc.code == 429:
            raise HTTPException(
                429, "Too many sign-in attempts. Wait before trying again."
            ) from None
        if exc.code in (400, 401, 403, 422):
            raise HTTPException(
                401, "Sign-in details or session are invalid. Please try again."
            ) from None
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    except (OSError, ValueError):
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None


def _public_session(data: dict) -> dict:
    try:
        access, refresh = data["access_token"], data["refresh_token"]
        if not isinstance(access, str) or not 1 <= len(access) <= 8192:
            raise ValueError("Invalid access token")
        if not isinstance(refresh, str) or not 1 <= len(refresh) <= 8192:
            raise ValueError("Invalid refresh token")
        user = data["user"]
        owner = str(uuid.UUID(user["id"]))
        if user.get("is_anonymous") is not False:
            raise ValueError("Unverified account")
        duration = int(data["expires_in"])
        if not 1 <= duration <= 86400:
            raise ValueError("Invalid expiry")
        # Fully verify identity and current session before returning a usable session.
        verified = require_research_owner("Bearer " + access)
        if verified.id != owner:
            raise ValueError("Identity mismatch")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, "Authentication returned an unusable session.") from None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(time.time()) + duration,
        "user": {"id": owner, "email": str(user.get("email") or "")[:320]},
    }


async def _auth_input(req: Request) -> dict:
    # Explicit parsing keeps credentials out of FastAPI validation error bodies.
    raw = await req.body()
    if len(raw) > 16384:
        raise HTTPException(413, "Sign-in request is too large.")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid body")
        return data
    except (ValueError, TypeError):
        raise HTTPException(422, "Check the sign-in fields.") from None


@router.get("/status")
def auth_status():
    return {
        "configured": bool(SETTINGS.supabase_url and SETTINGS.supabase_service_key),
        "account_creation": False,
    }


@router.post("/sign-in")
async def sign_in(req: Request):
    data = await _auth_input(req)
    email, password = data.get("email"), data.get("password")
    if (
        not isinstance(email, str)
        or not 3 <= len(email) <= 320
        or "@" not in email
        or not isinstance(password, str)
        or not 1 <= len(password) <= 1024
    ):
        raise HTTPException(422, "Enter your email and password.")
    data = await run_in_threadpool(
        _auth_exchange, "token?grant_type=password", {"email": email.strip(), "password": password}
    )
    return await run_in_threadpool(_public_session, data)


@router.post("/refresh")
async def refresh(req: Request):
    data = await _auth_input(req)
    token = data.get("refresh_token")
    if not isinstance(token, str) or not 1 <= len(token) <= 8192:
        raise HTTPException(422, "A refresh session is required.")
    data = await run_in_threadpool(
        _auth_exchange, "token?grant_type=refresh_token", {"refresh_token": token}
    )
    return await run_in_threadpool(_public_session, data)


@router.post("/sign-out")
def sign_out(authorization: str = Header(default="")):
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 8192:
        raise HTTPException(401, "A current session is required.")
    _auth_exchange("logout?scope=local", token=parts[1])
    return {"signed_out": True}
