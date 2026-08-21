import logging
import time

import pytest

from app import payment_service as module
from app.payment_service import ExecutionMandate, PaymentExecutionError, PaymentService
from app.payment_vault import LithicCredentialProvider, PaymentMethod, ProvisionedCard, public


def mandate(nonce: str = "a" * 64) -> ExecutionMandate:
    return ExecutionMandate(
        user_id="thread-user",
        merchant="DigiKey Sandbox",
        amount_cents=760,
        currency="USD",
        items=(("HC-SR04", 2),),
        expires_at_epoch=int(time.time()) + 600,
        nonce=nonce,
    )


@pytest.mark.asyncio
async def test_lithic_provider_public_metadata_excludes_sensitive_values(
    monkeypatch, caplog
) -> None:
    provider = LithicCredentialProvider("secret-api-key", "https://sandbox.lithic.com/v1")
    method = provider.create_payment_method()
    responses = iter(
        [
            {"token": "lithic-card-token", "last_four": "4242"},
            {"token": "sensitive-transaction-token"},
        ]
    )

    async def fake_post(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(provider, "_post", fake_post)

    async def fake_get(*_args, **_kwargs):
        return {"pan": "4111111111114242", "cvv": "987", "token": "lithic-card-token"}

    monkeypatch.setattr(provider, "_get", fake_get)
    caplog.set_level(logging.INFO, logger="payment.audit")
    card = await provider.provision_for_payment(method.payment_method_id, 760, "request-id")
    await provider.authorize_sandbox(card, 760, "DigiKey Sandbox")

    visible = repr(public(provider.resolve(method.payment_method_id))) + caplog.text
    for secret in (
        "4111111111114242",
        "987",
        "lithic-card-token",
        "sensitive-transaction-token",
        "secret-api-key",
    ):
        assert secret not in visible
    assert "4242" in visible


@pytest.mark.asyncio
async def test_payment_service_sends_no_lithic_secret_to_digikey(monkeypatch, caplog) -> None:
    sensitive = ProvisionedCard("4111111111114242", "lithic-card-token")

    class FakeProvider:
        def resolve(self, payment_method_id):
            return PaymentMethod(payment_method_id, "lithic-card-token", "Virtual Visa", "4242")

        async def provision_for_payment(self, *_args):
            return sensitive

        async def authorize_sandbox(self, card, *_args):
            assert card is sensitive
            return "sensitive-transaction-token"

    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"order_id": "DKS-1", "status": "submitted"}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, path, json):
            sent.update({"path": path, "json": json})
            return Response()

    monkeypatch.setattr(module, "provider", FakeProvider())
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    service = PaymentService()
    caplog.set_level(logging.INFO, logger="payment.audit")
    result = await service.execute(
        proposal_id="PROP-1",
        approval_token="approval-proof",
        payment_method_id="pm_safe",
        mandate=mandate(),
    )

    assert result["order_id"] == "DKS-1"
    exposed = repr(sent) + caplog.text
    assert sent["json"]["payment_reference"] == "lithic_sandbox_authorized"
    for secret in (sensitive.pan, "987", sensitive.token, "sensitive-transaction-token"):
        assert secret not in exposed

    with pytest.raises(PaymentExecutionError, match="already been used"):
        await service.execute(
            proposal_id="PROP-1",
            approval_token="approval-proof",
            payment_method_id="pm_safe",
            mandate=mandate(),
        )


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("user_id", "", "user"),
        ("merchant", "Other", "merchant"),
        ("amount_cents", 0, "amount"),
        ("items", (), "items"),
        ("expires_at_epoch", 1, "expired"),
        ("nonce", "bad", "nonce"),
    ],
)
def test_mandate_policy_rejects_invalid_fields(field, value, message) -> None:
    values = mandate().__dict__ | {field: value}
    with pytest.raises(PaymentExecutionError, match=message):
        PaymentService()._validate(ExecutionMandate(**values))
