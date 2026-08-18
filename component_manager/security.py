"""HMAC-signed approval tokens binding a purchase proposal to its total.

The DigiKey order flow only accepts a token minted for the exact proposal
for the exact proposal_id/total/expires_at on file, so an approval cannot be
replayed against a proposal whose total or expiry has since changed.
"""

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from component_manager.config import settings


def _require_secret() -> str:
    if settings.approval_token_secret:
        return settings.approval_token_secret
    path = Path("component_manager/data/.approval_key")
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    path.write_text(secret)
    os.chmod(path, 0o600)
    return secret


def sign_proposal(proposal_id: str, total: float, expires_at: str) -> str:
    """Mint an approval token bound to one proposal's id, total, and expiry."""

    secret = _require_secret()
    message = f"{proposal_id}:{total:.2f}:{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_proposal(proposal_id: str, total: float, expires_at: str, token: str) -> bool:
    """Check that a token matches the proposal it claims to approve."""

    expected = sign_proposal(proposal_id, total, expires_at)
    return hmac.compare_digest(expected, token)
