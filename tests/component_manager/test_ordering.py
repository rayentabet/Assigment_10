from urllib.parse import parse_qs, urlparse

import pytest

from component_manager import oauth, purchasing
from component_manager.config import settings


@pytest.mark.asyncio
async def test_three_legged_oauth_encrypts_and_loads_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "digikey_order_client_id", "sandbox-client")
    monkeypatch.setattr(settings, "digikey_order_client_secret", "sandbox-secret")
    monkeypatch.setattr(settings, "digikey_order_sandbox", True)
    monkeypatch.setattr(settings, "oauth_key_path", tmp_path / ".oauth_key")

    async def fake_token_request(data: dict[str, str]) -> dict:
        assert data["grant_type"] == "authorization_code"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 1800,
        }

    monkeypatch.setattr(oauth, "_token_request", fake_token_request)
    url = await oauth.authorization_url()
    state = parse_qs(urlparse(url).query)["state"][0]
    await oauth.exchange_code("one-minute-code", state)

    status = await oauth.connection_status()
    assert status["connected"] is True
    assert await oauth.access_token() == "access-token"


def test_ap2_checkout_mandate_requires_human_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(purchasing, "_AP2_KEY_PATH", tmp_path / ".ap2_key.pem")
    expires = purchasing._now() + purchasing.timedelta(minutes=15)
    card = {
        "digikey_part_number": "TEST-ND",
        "manufacturer_part_number": "TEST",
        "currency": "USD",
        "total_price": 10.0,
    }

    mandates = purchasing._mandates(card, 2, "DKP-test", expires)

    assert mandates["intent"]["user_cart_confirmation_required"] is True
    assert mandates["cart"]["contents"]["user_cart_confirmation_required"] is True
    assert mandates["checkout_mandate_sdjwt"]
