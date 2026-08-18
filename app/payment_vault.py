"""Ephemeral sandbox Credential Provider isolated from agent prompts and storage."""

import secrets
import time
from dataclasses import dataclass


class CredentialError(ValueError):
    """Safe validation failure for the sandbox payment form."""


@dataclass(frozen=True)
class Credential:
    """Non-sensitive payment reference retained only in process memory."""

    brand: str
    last4: str
    expires_at: int


_CREDENTIAL_TTL_SECONDS = 8 * 60 * 60
_credentials: dict[str, Credential] = {}


def _digits(value: str) -> str:
    """Remove display separators without retaining the original card string."""

    return "".join(character for character in value if character.isdigit())


def _luhn(number: str) -> bool:
    """Validate a card number using the deterministic Luhn checksum."""

    total = 0
    parity = len(number) % 2
    for index, character in enumerate(number):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _brand(number: str) -> str:
    """Return a display-only card brand from the test-card prefix."""

    if number.startswith("4"):
        return "Visa"
    if number[:2] in {str(value) for value in range(51, 56)}:
        return "Mastercard"
    return "Test card"


def tokenize(card_number: str, expiry: str, cvv: str) -> dict:
    """Validate sandbox card fields, discard them, and return an opaque reference."""

    number = _digits(card_number)
    cvv_digits = _digits(cvv)
    if number != "4242424242424242":
        raise CredentialError("Use sandbox test card 4242 4242 4242 4242.")
    if not _luhn(number):
        raise CredentialError("The sandbox card number is invalid.")
    if len(cvv_digits) != 3:
        raise CredentialError("The sandbox CVV must contain three digits.")
    parts = expiry.strip().split("/")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise CredentialError("Expiry must use MM/YY format.")
    month, year = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12 or year < 26:
        raise CredentialError("Use a valid future sandbox expiry.")

    credential_id = f"cp_test_{secrets.token_urlsafe(18)}"
    credential = Credential(
        brand=_brand(number),
        last4=number[-4:],
        expires_at=int(time.time()) + _CREDENTIAL_TTL_SECONDS,
    )
    _credentials[credential_id] = credential
    return {
        "credential_id": credential_id,
        "brand": credential.brand,
        "last4": credential.last4,
        "expires_at": credential.expires_at,
        "sandbox": True,
    }


def authorize(credential_id: str) -> Credential:
    """Resolve a reusable session credential only while it remains valid."""

    credential = _credentials.get(credential_id)
    if credential is None:
        raise CredentialError("The sandbox payment credential is unknown.")
    if credential.expires_at < int(time.time()):
        _credentials.pop(credential_id, None)
        raise CredentialError("The sandbox payment credential has expired.")
    return credential


def forget(credential_id: str) -> bool:
    """Remove one reusable sandbox payment method from process memory."""

    return _credentials.pop(credential_id, None) is not None


def clear() -> None:
    """Erase all ephemeral credentials during shutdown and isolated tests."""

    _credentials.clear()
