import httpx
import pytest

from component_manager import tools
from component_manager.config import settings
from component_manager.digikey import DigiKeyClient, normalize_product, rank_products


def _product(part: str, price: float, stock: int) -> dict:
    return {
        "DigiKeyProductNumber": part,
        "ManufacturerProductNumber": f"MFG-{part}",
        "Manufacturer": {"Name": "Example Components"},
        "Description": {"ProductDescription": "Distance sensor"},
        "QuantityAvailable": stock,
        "ProductUrl": f"https://example.test/{part}",
        "PhotoUrl": f"https://example.test/{part}.jpg",
        "DatasheetUrl": f"https://example.test/{part}.pdf",
        "ProductVariations": [
            {
                "DigiKeyProductNumber": part,
                "StandardPricing": [
                    {"BreakQuantity": 1, "UnitPrice": str(price)},
                    {"BreakQuantity": 10, "UnitPrice": str(price * 0.8)},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_client_uses_two_legged_oauth_and_caches_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "digikey_client_id", "client-id")
    monkeypatch.setattr(settings, "digikey_client_secret", "client-secret")
    monkeypatch.setattr(settings, "digikey_sandbox", True)
    token_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/v1/oauth2/token":
            token_calls += 1
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "token", "expires_in": 600})
        assert request.headers["Authorization"] == "Bearer token"
        assert request.headers["X-DIGIKEY-Client-Id"] == "client-id"
        return httpx.Response(200, json={"Products": []})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DigiKeyClient(http)
    await client.search("ultrasonic sensor")
    await client.search("servo motor")

    assert token_calls == 1
    await http.aclose()


def test_normalize_product_uses_requested_quantity_price_break() -> None:
    card = normalize_product(_product("SENSOR-1", 2.5, 20), quantity=10)

    assert card["digikey_part_number"] == "SENSOR-1"
    assert card["unit_price"] == 2.0
    assert card["total_price"] == 20.0
    assert card["quantity_available"] == 20


def test_rank_products_prefers_in_stock_then_lowest_total() -> None:
    cards = [
        normalize_product(_product("EXPENSIVE", 4.0, 20), 2),
        normalize_product(_product("CHEAP", 2.0, 20), 2),
        normalize_product(_product("NO-STOCK", 1.0, 0), 2),
    ]

    ranked = rank_products(cards)

    assert [card["digikey_part_number"] for card in ranked] == [
        "CHEAP",
        "EXPENSIVE",
        "NO-STOCK",
    ]


@pytest.mark.asyncio
async def test_search_tool_returns_ranked_product_cards(monkeypatch) -> None:
    async def fake_search(query: str, quantity: int, limit: int) -> dict:
        assert query == "ultrasonic sensor"
        assert quantity == 2
        assert limit == 3
        return {
            "Products": [
                _product("EXPENSIVE", 4.0, 20),
                _product("CHEAP", 2.0, 20),
                _product("NO-STOCK", 1.0, 0),
            ]
        }

    monkeypatch.setattr(tools.digikey_client, "search", fake_search)
    result = await tools.search_digikey("ultrasonic sensor", quantity=2, limit=3)

    assert result["success"] is True
    assert result["offer_count"] == 2
    assert result["best_offer"]["digikey_part_number"] == "CHEAP"
    assert result["offers"][0]["image_url"].endswith("CHEAP.jpg")
