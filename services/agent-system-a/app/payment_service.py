"""Deterministic mandate validation and payment execution; no LLM is involved."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.config import settings
from app.payment_vault import CredentialError, SandboxCredentialProvider, provider

audit = logging.getLogger("payment.audit")


class PaymentExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionMandate:
    user_id: str
    merchant: str
    amount_cents: int
    currency: str
    items: tuple[tuple[str, int], ...]
    expires_at_epoch: int
    nonce: str


class PaymentService:
    def __init__(self) -> None:
        self._used_nonces: set[str] = set()
        self._execution_lock = asyncio.Lock()

    def _validate(self, mandate: ExecutionMandate) -> None:
        if not mandate.user_id or len(mandate.user_id) > 128:
            raise PaymentExecutionError("The mandate user is invalid.")
        if mandate.merchant != "DigiKey Sandbox":
            raise PaymentExecutionError("The mandate merchant is invalid.")
        if mandate.amount_cents <= 0:
            raise PaymentExecutionError("The mandate amount is invalid.")
        if mandate.currency != "USD":
            raise PaymentExecutionError("Lithic Sandbox supports this flow only in USD.")
        if not mandate.items or any(not item or quantity < 1 for item, quantity in mandate.items):
            raise PaymentExecutionError("The mandate items are invalid.")
        if mandate.expires_at_epoch <= int(time.time()):
            raise PaymentExecutionError("The mandate has expired.")
        if len(mandate.nonce) != 64 or any(c not in "0123456789abcdef" for c in mandate.nonce):
            raise PaymentExecutionError("The mandate nonce is invalid.")
        if mandate.nonce in self._used_nonces:
            raise PaymentExecutionError("The mandate has already been used.")

    async def execute(
        self,
        *,
        proposal_id: str,
        approval_token: str,
        payment_method_id: str,
        mandate: ExecutionMandate,
    ) -> dict:
        # Serialize validation + commit so concurrent resumes cannot race the
        # already-used check within this process.
        async with self._execution_lock:
            return await self._execute_locked(
                proposal_id=proposal_id,
                approval_token=approval_token,
                payment_method_id=payment_method_id,
                mandate=mandate,
            )

    async def _execute_locked(
        self,
        *,
        proposal_id: str,
        approval_token: str,
        payment_method_id: str,
        mandate: ExecutionMandate,
    ) -> dict:
        self._validate(mandate)
        method = provider.resolve(payment_method_id)
        if not approval_token:
            raise PaymentExecutionError("The AP2 approval token is missing.")
        try:
            card = await provider.provision_for_payment(
                payment_method_id,
                mandate.amount_cents,
                str(uuid5(NAMESPACE_URL, mandate.nonce)),
            )
            await provider.authorize_sandbox(card, mandate.amount_cents, mandate.merchant)
        except CredentialError as error:
            raise PaymentExecutionError(str(error)) from error

        # DigiKey Sandbox Ordering accepts no card fields. Lithic authorization
        # is a parallel simulation and must not be represented as a real charge.
        reference = method.provider_reference
        if not isinstance(provider, SandboxCredentialProvider):
            reference = "lithic_sandbox_authorized"
        try:
            async with httpx.AsyncClient(
                base_url=settings.component_manager_rest_url, timeout=30.0
            ) as client:
                response = await client.post(
                    "/internal/digikey/orders",
                    json={
                        "proposal_id": proposal_id,
                        "approval_token": approval_token,
                        "idempotency_key": mandate.nonce,
                        "payment_reference": reference,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise PaymentExecutionError("DigiKey sandbox order validation failed.") from error
        except httpx.HTTPError as error:
            raise PaymentExecutionError("Component Manager is unreachable.") from error
        self._used_nonces.add(mandate.nonce)
        audit.info(
            "payment_executed provider=%s payment_method_id=%s proposal_id=%s mandate=%s",
            settings.payment_provider,
            payment_method_id,
            proposal_id,
            hashlib.sha256(mandate.nonce.encode()).hexdigest()[:12],
        )
        order = response.json()
        safe_method = provider.resolve(payment_method_id)
        return {
            "order_id": order.get("order_id"),
            "status": order.get("status"),
            "payment_method_id": safe_method.payment_method_id,
            "payment_display": safe_method.display,
        }

    def clear_replay_cache(self) -> None:
        self._used_nonces.clear()


payment_service = PaymentService()
