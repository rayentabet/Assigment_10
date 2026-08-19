"""The Component Manager tools exposed to the Google ADK agent.

These are plain functions (not decorator-wrapped) because google-adk's
FunctionTool introspects a callable's type hints and docstring directly.
Every deterministic business rule (spending limit, expiry, idempotency,
approval-token binding) lives here rather than in the agent's prompt, so it
holds even if the model misbehaves.
"""

from component_manager.config import settings
from component_manager.digikey import DigiKeyError, normalize_product, rank_products
from component_manager.digikey import client as digikey_client
from component_manager.purchasing import PurchaseError
from component_manager.purchasing import create_proposal as create_digikey_purchase
from component_manager.purchasing import order_status as read_digikey_order
from component_manager.purchasing import place_order as submit_digikey_order


async def search_digikey(query: str, quantity: int = 1, limit: int = 5) -> dict:
    """Search DigiKey for in-stock component offers and return ranked product cards.

    This tool is read-only: it searches the external DigiKey catalog but cannot
    create a cart, place an order, or access payment credentials.

    Args:
        query: Component name, description, manufacturer part number, or DigiKey part number.
        quantity: Desired number of units, used to select the applicable price break.
        limit: Maximum number of offers to return, from 1 to 10.
    """

    try:
        payload = await digikey_client.search(query=query, quantity=quantity, limit=limit)
    except DigiKeyError as error:
        return {"success": False, "query": query, "error": str(error)}

    raw_products = payload.get("Products") or payload.get("products") or []
    offers = rank_products(
        [normalize_product(product, quantity) for product in raw_products]
    )
    offers = [offer for offer in offers if offer["quantity_available"] >= quantity][:limit]
    return {
        "success": True,
        "query": query,
        "requested_quantity": quantity,
        "offer_count": len(offers),
        "best_offer": offers[0] if offers else None,
        "offers": offers,
        "source": "DigiKey Product Information V4",
        "sandbox": settings.digikey_sandbox,
    }


async def create_digikey_proposal(part_number: str, quantity: int) -> dict:
    """Create an AP2-bound DigiKey sandbox proposal requiring human confirmation.

    Args:
        part_number: Exact DigiKey part number selected from search_digikey.
        quantity: Positive number of units requested by the user.
    """

    try:
        return await create_digikey_purchase(part_number, quantity)
    except PurchaseError as error:
        return {"success": False, "error": str(error)}


async def place_digikey_order(
    proposal_id: str,
    approval_token: str,
    idempotency_key: str,
    payment_credential_id: str,
) -> dict:
    """Submit one approved proposal to DigiKey sandbox using AP2 and OAuth.

    Never call this before the host application's human-approval interrupt has
    returned the exact approval token and an idempotency key.

    Args:
        proposal_id: Identifier returned by create_digikey_proposal.
        approval_token: Exact token returned with that proposal after human review.
        idempotency_key: Stable key supplied by System A to prevent duplicate orders.
        payment_credential_id: Opaque AP2 sandbox credential reference; never raw card data.
    """

    try:
        return await submit_digikey_order(
            proposal_id,
            approval_token,
            idempotency_key,
            payment_credential_id,
        )
    except PurchaseError as error:
        return {"success": False, "error": str(error)}


async def get_digikey_order(order_id: str) -> dict:
    """Return the status and supplier reference for a DigiKey sandbox order.

    Args:
        order_id: Internal sandbox order identifier returned by place_digikey_order.
    """

    return await read_digikey_order(order_id)
