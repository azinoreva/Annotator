"""
Annotator authentication against the aggregator server.

Handles logging in and keeping a fresh access token. Tokens are cached in
memory (module-level); nothing is written to disk.

    await login.configure(...)   # optional: override creds/base url
    token = await login.ensure_token()   ->  valid Bearer token
"""

from __future__ import annotations

import os
import time
import logging
from typing import Optional

import httpx


log = logging.getLogger("annotator.login")

BASE_URL = os.getenv("Aggregator_base_url", "http://127.0.0.1:8000")
LOGIN_PATH = "/api/annotator_login"
REFRESH_PATH = "/api/annotator_refresh"

# Server issues annotator access tokens with a 24*60*10 minute lifetime.
ACCESS_TTL = 10 * 24 * 60 * 60
REFRESH_BEFORE = ACCESS_TTL * 0.8

_annotator_id: Optional[str] = os.getenv("ANOTATOR_ID")
_annotator_password: Optional[str] = os.getenv("ANOTATOR_PASSWORD")
_base_url: str = BASE_URL

_access_token: Optional[str] = None
_refresh_token: Optional[str] = None
_acquired_at: float = 0.0


def configure(
    *,
    annotator_id: Optional[str] = None,
    annotator_password: Optional[str] = None,
    base_url: Optional[str] = None,
) -> None:
    """Override login credentials / server url, then drop cached tokens."""
    global _annotator_id, _annotator_password, _base_url
    global _access_token, _refresh_token, _acquired_at

    if annotator_id is not None:
        _annotator_id = annotator_id
    if annotator_password is not None:
        _annotator_password = annotator_password
    if base_url is not None:
        _base_url = base_url

    _access_token = None
    _refresh_token = None
    _acquired_at = 0.0


def is_configured() -> bool:
    """Whether login credentials have been provided (not whether login works)."""
    return bool(_annotator_id and _annotator_password)


async def login() -> dict:
    """Log in and cache the returned tokens. Raises on non-2xx."""
    if not _annotator_id or not _annotator_password:
        raise RuntimeError(
            "Annotator credentials are not configured — set ANOTATOR_ID / "
            "ANOTATOR_PASSWORD or call login.configure() first."
        )

    url = f"{_base_url}{LOGIN_PATH}"
    body = {
        "annotator_id": _annotator_id,
        "annotator_password": _annotator_password,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()

    data = r.json()
    _cache_tokens(data)
    log.info("Annotator login succeeded against %s.", _base_url)
    return data


async def refresh() -> dict:
    """Exchange the refresh token for fresh tokens; falls back to login()."""
    if not _refresh_token:
        return await login()

    url = f"{_base_url}{REFRESH_PATH}"
    headers = {
        "Authorization": f"Bearer {_refresh_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers)

    if r.status_code in (401, 403) or r.is_error:
        log.warning("Token refresh failed (%s) — re-logging in.", r.status_code)
        _clear_tokens()
        return await login()

    data = r.json()
    _cache_tokens(data)
    log.info("Annotator tokens refreshed.")
    return data


async def ensure_token() -> str:
    """Return a cached/valid access token, logging in or refreshing as needed."""
    if _access_token and (time.time() - _acquired_at) < REFRESH_BEFORE:
        return _access_token

    if time.time() - _acquired_at < ACCESS_TTL:
        try:
            await refresh()
            if _access_token:
                return _access_token
        except Exception:
            log.exception("Token refresh failed; attempting fresh login.")
            _clear_tokens()

    # No valid cached token (or refresh failed) -> fresh login.
    data = await login()
    return data["access_token"]


async def force_relogin() -> str:
    """Drop cached tokens and log in again from scratch."""
    _clear_tokens()
    data = await login()
    return data["access_token"]


def _cache_tokens(data: dict) -> None:
    global _access_token, _refresh_token, _acquired_at
    _access_token = data.get("access_token")
    _refresh_token = data.get("refresh_token") or _refresh_token
    _acquired_at = time.time()


def _clear_tokens() -> None:
    global _access_token, _refresh_token, _acquired_at
    _access_token = None
    _refresh_token = None
    _acquired_at = 0.0