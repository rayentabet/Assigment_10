"""Read-only DigiKey Product Information V4 client.

The client uses the OAuth 2.0 client-credentials flow. Access tokens remain in
this backend process and are refreshed shortly before they expire; credentials
and tokens are never included in agent tool results.
"""

import asyncio
import time
from typing import Any

import httpx

from component_manager.config import settings


class DigiKeyError(RuntimeError):
    """A safe, user-displayable DigiKey configuration or API error."""


class DigiKeyClient:
    """Authenticate with DigiKey and perform read-only product searches."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        host = "sandbox-api.digikey.com" if settings.digikey_sandbox else "api.digikey.com"
        return f"https://{host}"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.digikey_timeout_seconds)
        return self._client

    def _check_config(self) -> None:
        if not settings.digikey_client_id or not settings.digikey_client_secret:
            raise DigiKeyError(
                "DigiKey is not configured. Set DIGIKEY_CLIENT_ID and "
                "DIGIKEY_CLIENT_SECRET in .env."
            )

    async def _access_token(self) -> str:
        self._check_config()
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            try:
                response = await self._http().post(
                    f"{self.base_url}/v1/oauth2/token",
                    data={
                        "client_id": settings.digikey_client_id,
                        "client_secret": settings.digikey_client_secret,
                        "grant_type": "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as error:
                raise DigiKeyError(
                    f"DigiKey authentication failed with HTTP {error.response.status_code}."
                ) from error
            except (httpx.HTTPError, ValueError) as error:
                raise DigiKeyError("DigiKey authentication is currently unavailable.") from error

            token = payload.get("access_token")
            if not token:
                raise DigiKeyError("DigiKey authentication returned no access token.")

            expires_in = max(int(payload.get("expires_in", 600)), 1)
            self._token = str(token)
            # Refresh early so a token cannot expire during the following API call.
            self._token_expires_at = time.monotonic() + max(expires_in - 30, 1)
            return self._token

    async def search(self, query: str, quantity: int = 1, limit: int = 5) -> dict:
        """Search DigiKey and return its raw Product Information V4 response."""

        query = query.strip()
        if not query:
            raise DigiKeyError("The DigiKey search query cannot be empty.")
        if quantity < 1:
            raise DigiKeyError("Quantity must be at least 1.")
        limit = min(max(limit, 1), 10)

        token = await self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": settings.digikey_client_id,
            "X-DIGIKEY-Locale-Site": settings.digikey_site,
            "X-DIGIKEY-Locale-Language": settings.digikey_language,
            "X-DIGIKEY-Locale-Currency": settings.digikey_currency,
            "Accept": "application/json",
        }
        if settings.digikey_account_id:
            headers["X-DIGIKEY-Account-Id"] = settings.digikey_account_id

        body = {
            "Keywords": query,
            "Limit": limit,
            "Offset": 0,
        }
        try:
            response = await self._http().post(
                f"{self.base_url}/products/v4/search/keyword",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                # Force a fresh token on the next request without exposing the response body.
                self._token = ""
                self._token_expires_at = 0.0
            raise DigiKeyError(f"DigiKey product search failed with HTTP {status}.") from error
        except (httpx.HTTPError, ValueError) as error:
            raise DigiKeyError("DigiKey product search is currently unavailable.") from error


def _text(value: Any) -> str | None:
    """Extract display text from either a string or DigiKey description object."""

    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("ProductDescription", "DetailedDescription", "Name"):
            if value.get(key):
                return str(value[key])
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(prices: list[dict], quantity: int) -> float | None:
    """Choose the applicable standard-price break for the requested quantity."""

    parsed = [
        (int(item.get("BreakQuantity", 0)), _number(item.get("UnitPrice")))
        for item in prices
        if _number(item.get("UnitPrice")) is not None
    ]
    eligible = [item for item in parsed if item[0] <= quantity]
    selected = max(eligible or parsed, key=lambda item: item[0], default=None)
    return selected[1] if selected else None


def _variation(product: dict, quantity: int) -> dict:
    variations = product.get("ProductVariations") or product.get("Variations") or []
    candidates = []
    for variation in variations:
        price = _price(variation.get("StandardPricing") or [], quantity)
        candidates.append((price is None, price or float("inf"), variation))
    return min(candidates, default=(True, float("inf"), {}))[2]


def normalize_product(product: dict, quantity: int) -> dict:
    """Convert one DigiKey product into the stable product-card schema."""

    variation = _variation(product, quantity)
    unit_price = _number(variation.get("UnitPrice"))
    if unit_price is None:
        unit_price = _price(variation.get("StandardPricing") or [], quantity)
    if unit_price is None:
        unit_price = _number(product.get("UnitPrice"))

    manufacturer = product.get("Manufacturer") or {}
    available = product.get("QuantityAvailable")
    if available is None:
        available = variation.get("QuantityAvailable", 0)

    part_number = (
        variation.get("DigiKeyProductNumber")
        or product.get("DigiKeyProductNumber")
        or product.get("ManufacturerProductNumber")
    )
    return {
        "supplier": "DigiKey",
        "digikey_part_number": part_number,
        "manufacturer_part_number": product.get("ManufacturerProductNumber"),
        "manufacturer": (
            manufacturer.get("Name") if isinstance(manufacturer, dict) else manufacturer
        ),
        "description": _text(product.get("Description")),
        "quantity_available": int(available or 0),
        "requested_quantity": quantity,
        "unit_price": unit_price,
        "total_price": round(unit_price * quantity, 4) if unit_price is not None else None,
        "currency": settings.digikey_currency,
        "product_url": product.get("ProductUrl"),
        "image_url": product.get("PhotoUrl") or product.get("PrimaryPhoto"),
        "datasheet_url": product.get("DatasheetUrl"),
    }


def rank_products(products: list[dict]) -> list[dict]:
    """Rank purchasable, in-stock products by total price, preserving relevance ties."""

    return sorted(
        products,
        key=lambda item: (
            item["quantity_available"] < item["requested_quantity"],
            item["total_price"] is None,
            item["total_price"] if item["total_price"] is not None else float("inf"),
        ),
    )


client = DigiKeyClient()
