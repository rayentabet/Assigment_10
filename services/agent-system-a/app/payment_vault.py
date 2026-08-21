"""Credential providers and the private payment-method map.

Sensitive Lithic responses exist only inside ``LithicCredentialProvider`` and
are never returned by its public methods.
"""

from __future__ import annotations

import logging
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

import httpx

from app.config import settings

audit = logging.getLogger("payment.audit")


class CredentialError(ValueError):
    """Safe credential/provider failure with no upstream response content."""


@dataclass(frozen=True)
class PaymentMethod:
    payment_method_id: str
    provider_reference: str | None
    brand: str
    last4: str | None
    expires_at: int | None = None

    @property
    def display(self) -> str:
        return f"{self.brand} ending {self.last4}" if self.last4 else self.brand


@dataclass(frozen=True)
class ProvisionedCard:
    """Sensitive execution-only value. Never serialize or log this object."""

    pan: str
    token: str


class CredentialProvider(ABC):
    @abstractmethod
    def create_payment_method(self) -> PaymentMethod: ...

    @abstractmethod
    def resolve(self, payment_method_id: str) -> PaymentMethod: ...

    @abstractmethod
    async def provision_for_payment(
        self, payment_method_id: str, amount_cents: int, idempotency_key: str
    ) -> ProvisionedCard | None: ...

    @abstractmethod
    async def authorize_sandbox(
        self, card: ProvisionedCard | None, amount_cents: int, merchant: str
    ) -> str | None: ...

    @abstractmethod
    def forget(self, payment_method_id: str) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...


class _MemoryProvider(CredentialProvider):
    def __init__(self) -> None:
        self._methods: dict[str, PaymentMethod] = {}

    def _save(
        self,
        brand: str,
        last4: str | None = None,
        reference: str | None = None,
        expires_at: int | None = None,
    ) -> PaymentMethod:
        method = PaymentMethod(
            f"pm_{secrets.token_urlsafe(18)}", reference, brand, last4, expires_at
        )
        self._methods[method.payment_method_id] = method
        return method

    def resolve(self, payment_method_id: str) -> PaymentMethod:
        method = self._methods.get(payment_method_id)
        if method is None:
            raise CredentialError("The payment method is unknown.")
        if method.expires_at is not None and method.expires_at < int(time.time()):
            self._methods.pop(payment_method_id, None)
            raise CredentialError("The payment method has expired.")
        return method

    def forget(self, payment_method_id: str) -> bool:
        return self._methods.pop(payment_method_id, None) is not None

    def clear(self) -> None:
        self._methods.clear()


class LithicCredentialProvider(_MemoryProvider):
    """Issue and authorize Lithic Sandbox single-use virtual cards."""

    def __init__(self, api_key: str, base_url: str) -> None:
        super().__init__()
        if not api_key:
            raise RuntimeError("LITHIC_API_KEY is required when PAYMENT_PROVIDER=lithic.")
        if base_url.rstrip("/") != "https://sandbox.lithic.com/v1":
            raise RuntimeError("Lithic integration is sandbox-only; LITHIC_BASE_URL is invalid.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def create_payment_method(self) -> PaymentMethod:
        method = self._save("Lithic single-use Virtual Visa")
        audit.info(
            "payment_method_created provider=lithic payment_method_id=%s", method.payment_method_id
        )
        return method

    async def _post(self, path: str, payload: dict, idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": self._api_key, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=settings.lithic_timeout_seconds
            ) as client:
                response = await client.post(path, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            raise CredentialError(
                f"Lithic Sandbox {path} failed with HTTP {error.response.status_code}."
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            # Never include response bodies/headers: they may contain card data or request IDs.
            raise CredentialError(f"Lithic Sandbox {path} request failed.") from error

    async def _get(self, path: str) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=settings.lithic_timeout_seconds
            ) as client:
                response = await client.get(
                    path, headers={"Authorization": self._api_key, "Accept": "application/json"}
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as error:
            raise CredentialError(
                f"Lithic Sandbox card lookup failed with HTTP {error.response.status_code}."
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise CredentialError("Lithic Sandbox card lookup failed.") from error

    async def provision_for_payment(
        self, payment_method_id: str, amount_cents: int, idempotency_key: str
    ) -> ProvisionedCard:
        method = self.resolve(payment_method_id)
        payload = await self._post(
            "/cards",
            {
                "type": "SINGLE_USE",
                "spend_limit": amount_cents,
                "spend_limit_duration": "FOREVER",
            },
            idempotency_key=idempotency_key,
        )
        try:
            token = str(payload["token"])
            # Current Lithic responses may omit PAN/CVV from collection/create
            # metadata. Sandbox Get Card returns PAN for this specific card.
            if not payload.get("pan"):
                payload = await self._get(f"/cards/{token}")
            # CVV may be present in the upstream response, but this flow does
            # not require it, so it is deliberately neither read nor retained.
            card = ProvisionedCard(pan=str(payload["pan"]), token=token)
            last4 = card.pan[-4:]
            if len(card.pan) != 16 or not card.pan.isdigit() or len(last4) != 4:
                raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            raise CredentialError("Lithic returned an invalid card response.") from error
        self._methods[payment_method_id] = replace(
            method,
            provider_reference=card.token,
            last4=last4,
            brand="Lithic single-use Virtual Visa",
        )
        audit.info("virtual_card_issued provider=lithic payment_method_id=%s", payment_method_id)
        return card

    async def authorize_sandbox(
        self, card: ProvisionedCard | None, amount_cents: int, merchant: str
    ) -> str:
        if card is None:
            raise CredentialError("Lithic card was not provisioned.")
        payload = await self._post(
            "/simulate/authorize",
            {
                "amount": amount_cents,
                "descriptor": merchant[:25],
                "pan": card.pan,
                "merchant_acceptor_id": "DIGIKEYSANDBOX",
            },
        )
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise CredentialError("Lithic authorization simulation failed.")
        audit.info("sandbox_authorization_approved provider=lithic")
        return token


class SandboxCredentialProvider(_MemoryProvider):
    """Optional legacy provider, restricted to local development."""

    def create_payment_method(self) -> PaymentMethod:
        return self._save(
            "Local test Visa",
            "4242",
            f"cp_test_{secrets.token_urlsafe(18)}",
            int(time.time()) + 8 * 60 * 60,
        )

    def tokenize(self, card_number: str, expiry: str, cvv: str) -> PaymentMethod:
        number = "".join(c for c in card_number if c.isdigit())
        if number != "4242424242424242" or cvv != "123" or "/" not in expiry:
            raise CredentialError("Use the documented local sandbox card.")
        return self.create_payment_method()

    async def provision_for_payment(
        self, payment_method_id: str, amount_cents: int, idempotency_key: str
    ) -> None:
        self.resolve(payment_method_id)
        return None

    async def authorize_sandbox(self, card: None, amount_cents: int, merchant: str) -> None:
        return None


def _build_provider() -> CredentialProvider:
    if settings.payment_provider == "lithic":
        return LithicCredentialProvider(settings.lithic_api_key, settings.lithic_base_url)
    if settings.payment_provider == "sandbox" and settings.app_environment == "development":
        return SandboxCredentialProvider()
    raise RuntimeError("Use PAYMENT_PROVIDER=lithic, or sandbox only in development.")


provider = _build_provider()


def public(method: PaymentMethod) -> dict:
    return {
        "payment_method_id": method.payment_method_id,
        "display": method.display,
        "brand": method.brand,
        "last4": method.last4,
        "sandbox": True,
    }


def tokenize(card_number: str, expiry: str, cvv: str) -> dict:
    if not isinstance(provider, SandboxCredentialProvider):
        raise CredentialError("Raw-card tokenization is disabled for this provider.")
    result = public(provider.tokenize(card_number, expiry, cvv))
    result["credential_id"] = result["payment_method_id"]
    return result


def authorize(payment_method_id: str) -> PaymentMethod:
    return provider.resolve(payment_method_id)


def forget(payment_method_id: str) -> bool:
    return provider.forget(payment_method_id)


def clear() -> None:
    provider.clear()
