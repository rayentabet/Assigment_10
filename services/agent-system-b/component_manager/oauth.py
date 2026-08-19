"""Secure DigiKey three-legged OAuth for sandbox Ordering access."""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from component_manager.config import settings
from component_manager.db import get_db

_PROVIDER = "digikey_order"
_STATE_TTL_SECONDS = 600
_REFRESH_MARGIN_SECONDS = 60


class OAuthError(RuntimeError):
    """A safe OAuth error that contains no credentials or tokens."""


def _base_url() -> str:
    host = "sandbox-api.digikey.com" if settings.digikey_order_sandbox else "api.digikey.com"
    return f"https://{host}"


def _require_config() -> None:
    if not settings.digikey_order_client_id or not settings.digikey_order_client_secret:
        raise OAuthError("DigiKey Ordering OAuth is not configured.")
    if not settings.digikey_order_sandbox:
        raise OAuthError("Production ordering is disabled; DIGIKEY_ORDER_SANDBOX must be true.")


def _key() -> bytes:
    if settings.digikey_token_encryption_key:
        return settings.digikey_token_encryption_key.encode()

    path = Path(settings.oauth_key_path)
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def _fernet() -> Fernet:
    try:
        return Fernet(_key())
    except (ValueError, TypeError) as error:
        raise OAuthError("DIGIKEY_TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from error


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


async def authorization_url() -> str:
    """Create a one-use CSRF state and return DigiKey's authorization URL."""

    _require_config()
    state = secrets.token_urlsafe(32)
    db = await get_db()
    await db.save_oauth_state(_state_hash(state), int(time.time()) + _STATE_TTL_SECONDS)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.digikey_order_client_id,
            "redirect_uri": settings.digikey_order_redirect_uri,
            "state": state,
        }
    )
    return f"{_base_url()}/v1/oauth2/authorize?{query}"


async def exchange_code(code: str, state: str) -> None:
    """Validate callback state, exchange its short-lived code, and encrypt tokens."""

    _require_config()
    db = await get_db()
    valid_state = await db.consume_oauth_state(_state_hash(state), int(time.time()))
    if not valid_state:
        raise OAuthError("The DigiKey authorization state is invalid or expired.")

    payload = await _token_request(
        {
            "code": code,
            "client_id": settings.digikey_order_client_id,
            "client_secret": settings.digikey_order_client_secret,
            "redirect_uri": settings.digikey_order_redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    await _save_tokens(payload)


async def _token_request(data: dict[str, str]) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.digikey_timeout_seconds) as client:
            response = await client.post(f"{_base_url()}/v1/oauth2/token", data=data)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as error:
        raise OAuthError(
            f"DigiKey OAuth token exchange failed with HTTP {error.response.status_code}."
        ) from error
    except (httpx.HTTPError, ValueError) as error:
        raise OAuthError("DigiKey OAuth is currently unavailable.") from error
    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise OAuthError("DigiKey OAuth returned incomplete tokens.")
    return payload


async def _save_tokens(payload: dict) -> None:
    now = int(time.time())
    expires_at = now + int(payload.get("expires_in", 1800))
    stored = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_at": expires_at,
    }
    encrypted = _fernet().encrypt(json.dumps(stored).encode())
    db = await get_db()
    await db.save_oauth_tokens(_PROVIDER, encrypted, expires_at)


async def _load_tokens() -> dict | None:
    db = await get_db()
    row = await db.get_oauth_tokens(_PROVIDER)
    if row is None:
        return None
    try:
        return json.loads(_fernet().decrypt(row["encrypted_payload"]).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError) as error:
        raise OAuthError("Stored DigiKey authorization could not be decrypted.") from error


async def access_token() -> str:
    """Return a valid access token, rotating refresh tokens when required."""

    _require_config()
    tokens = await _load_tokens()
    if tokens is None:
        raise OAuthError("Connect a DigiKey sandbox account before placing an order.")
    if int(tokens["expires_at"]) > int(time.time()) + _REFRESH_MARGIN_SECONDS:
        return str(tokens["access_token"])

    payload = await _token_request(
        {
            "client_id": settings.digikey_order_client_id,
            "client_secret": settings.digikey_order_client_secret,
            "refresh_token": str(tokens["refresh_token"]),
            "grant_type": "refresh_token",
        }
    )
    await _save_tokens(payload)
    return str(payload["access_token"])


async def connection_status() -> dict:
    """Return connection metadata without decrypting or exposing tokens."""

    configured = bool(settings.digikey_order_client_id and settings.digikey_order_client_secret)
    db = await get_db()
    row = await db.get_oauth_tokens(_PROVIDER)
    return {
        "configured": configured,
        "connected": row is not None,
        "sandbox": settings.digikey_order_sandbox,
        "expires_at": row["expires_at"] if row else None,
    }


async def disconnect() -> None:
    db = await get_db()
    await db.delete_oauth_tokens(_PROVIDER)
