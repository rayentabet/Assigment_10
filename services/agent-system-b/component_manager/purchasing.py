"""AP2-authorized, sandbox-only DigiKey purchasing workflow."""

import base64
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from ap2.models.mandate import CartContents, CartMandate, IntentMandate
from ap2.models.payment_request import (
    PaymentCurrencyAmount,
    PaymentDetailsInit,
    PaymentItem,
    PaymentMethodData,
    PaymentRequest,
)
from ap2.sdk.generated.checkout_mandate import CheckoutMandate
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.mandate import MandateClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwcrypto import jwt
from jwcrypto.jwk import JWK

from component_manager import security
from component_manager.config import settings
from component_manager.db import get_db
from component_manager.digikey import DigiKeyError, normalize_product, rank_products
from component_manager.digikey import client as search_client
from component_manager.oauth import OAuthError, access_token

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_MANDATE_TTL_MINUTES = 15
_AP2_KEY_PATH = Path("component_manager/data/.ap2_key.pem")


class PurchaseError(RuntimeError):
    """A safe sandbox-purchasing error."""


def _now() -> datetime:
    return datetime.now(UTC)


def _ap2_key() -> JWK:
    if _AP2_KEY_PATH.exists():
        private_key = serialization.load_pem_private_key(_AP2_KEY_PATH.read_bytes(), None)
    else:
        private_key = ec.generate_private_key(ec.SECP256R1())
        _AP2_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AP2_KEY_PATH.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        os.chmod(_AP2_KEY_PATH, 0o600)
    key = JWK.from_pyca(private_key)
    key.update(kid="robotics-assistant-user")
    return key


def _checkout_jwt(cart: CartMandate, key: JWK) -> str:
    token = jwt.JWT(
        header={"alg": "ES256", "kid": "robotics-assistant-user"},
        claims=cart.model_dump_json(),
    )
    token.make_signed_token(key)
    return token.serialize()


def _hash(value: str) -> str:
    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _mandates(card: dict, quantity: int, proposal_id: str, expires_at: datetime) -> dict:
    amount = PaymentCurrencyAmount(currency=card["currency"], value=card["total_price"])
    line_item = PaymentItem(
        label=f"{quantity} × {card['manufacturer_part_number'] or card['digikey_part_number']}",
        amount=amount,
        refund_period=0,
    )
    payment_request = PaymentRequest(
        method_data=[PaymentMethodData(supported_methods="digikey-sandbox-account")],
        details=PaymentDetailsInit(
            id=proposal_id,
            display_items=[line_item],
            total=PaymentItem(label="DigiKey sandbox order total", amount=amount, refund_period=0),
        ),
    )
    intent = IntentMandate(
        user_cart_confirmation_required=True,
        natural_language_description=(
            f"Buy {quantity} unit(s) of DigiKey part {card['digikey_part_number']} "
            f"for no more than {card['total_price']:.2f} {card['currency']} in sandbox."
        ),
        merchants=["DigiKey Sandbox"],
        skus=[card["digikey_part_number"]],
        intent_expiry=expires_at.isoformat(),
    )
    cart = CartMandate(
        contents=CartContents(
            id=proposal_id,
            user_cart_confirmation_required=True,
            payment_request=payment_request,
            cart_expiry=expires_at.isoformat(),
            merchant_name="DigiKey Sandbox",
        )
    )
    key = _ap2_key()
    signed_checkout = _checkout_jwt(cart, key)
    checkout_hash = _hash(signed_checkout)
    checkout_mandate = CheckoutMandate(
        checkout_jwt=signed_checkout,
        checkout_hash=checkout_hash,
        iat=int(time.time()),
        exp=int(expires_at.timestamp()),
    )
    checkout_sdjwt = MandateClient().create(payloads=[checkout_mandate], issuer_key=key)
    return {
        "intent": intent.model_dump(mode="json"),
        "cart": cart.model_dump(mode="json"),
        "checkout_hash": checkout_hash,
        "checkout_mandate_sdjwt": checkout_sdjwt,
    }


async def create_proposal(part_number: str, quantity: int) -> dict:
    """Refresh one DigiKey offer and create an AP2-bound sandbox proposal."""

    if quantity < 1:
        raise PurchaseError("Quantity must be at least 1.")
    try:
        payload = await search_client.search(part_number, quantity=quantity, limit=5)
    except DigiKeyError as error:
        raise PurchaseError(str(error)) from error
    products = payload.get("Products") or []
    cards = rank_products([normalize_product(product, quantity) for product in products])
    exact = next(
        (card for card in cards if card["digikey_part_number"] == part_number),
        cards[0] if cards else None,
    )
    if exact is None or exact["unit_price"] is None:
        raise PurchaseError(f"No priced DigiKey offer was found for {part_number}.")
    if exact["quantity_available"] < quantity:
        raise PurchaseError(f"DigiKey does not have {quantity} units of {part_number} in stock.")

    proposal_id = f"DKP-{secrets.token_hex(6)}"
    expires_at = _now() + timedelta(minutes=_MANDATE_TTL_MINUTES)
    expires_text = expires_at.strftime(_TIMESTAMP_FORMAT)
    mandates = _mandates(exact, quantity, proposal_id, expires_at)
    approval_token = security.sign_proposal(proposal_id, exact["total_price"], expires_text)
    db = await get_db()
    await db.insert_digikey_proposal(
        proposal_id=proposal_id,
        part_number=exact["digikey_part_number"],
        manufacturer_part_number=exact["manufacturer_part_number"],
        component_name=exact["description"] or exact["digikey_part_number"],
        quantity=quantity,
        unit_price=exact["unit_price"],
        total=exact["total_price"],
        currency=exact["currency"],
        product_url=exact["product_url"],
        image_url=exact["image_url"],
        status="pending",
        approval_token=approval_token,
        expires_at=expires_text,
        mandate_json=json.dumps(mandates),
    )
    return {
        "success": True,
        "proposal_id": proposal_id,
        "component_id": exact["digikey_part_number"],
        "component_name": exact["description"],
        "quantity": quantity,
        "supplier_name": "DigiKey Sandbox",
        "unit_price": exact["unit_price"],
        "currency": exact["currency"],
        "fees": 0.0,
        "total": exact["total_price"],
        "delivery_estimate_days": None,
        "status": "pending",
        "approval_token": approval_token,
        "expires_at": expires_text,
        "product_url": exact["product_url"],
        "image_url": exact["image_url"],
        "ap2": {
            "intent_mandate": True,
            "checkout_mandate_signed": True,
            "human_confirmation_required": True,
        },
    }


def _payment_mandate(proposal: dict, mandates: dict, credential_id: str) -> str:
    now = int(time.time())
    payload = PaymentMandate(
        transaction_id=mandates["checkout_hash"],
        payee=Merchant(id="digikey-sandbox", name="DigiKey Sandbox", website="https://digikey.com"),
        payment_amount=Amount(
            amount=round(float(proposal["total"]) * 100), currency=proposal["currency"]
        ),
        payment_instrument=PaymentInstrument(
            id=credential_id,
            type="account",
            description="Tokenized human-present sandbox card credential",
        ),
        iat=now,
        exp=now + (_MANDATE_TTL_MINUTES * 60),
    )
    return MandateClient().create(payloads=[payload], issuer_key=_ap2_key())


def _order_body(proposal: dict, order_id: str) -> dict:
    address = {
        "Company": "Robotics Assistant Sandbox",
        "FirstName": "Sandbox",
        "LastName": "User",
        "Email": "sandbox@example.com",
        "AddressLineOne": "100 Test Street",
        "City": "Bloomington",
        "Province": "MN",
        "PostalCode": "55425",
        "Country": "US",
    }
    contact = {
        "CustomerId": "0",
        "Name": "Sandbox User",
        "Address": address,
        "Telephone": "555-0100",
    }
    return {
        "PurchaseOrderNumber": order_id,
        "Currency": proposal["currency"],
        "ShipControl": "Immediate",
        "MfgCOfCRequired": False,
        "BuyerContact": contact,
        "ShippingContact": contact,
        "BillingAccount": 0,
        "ShipMethod": "FedEx Ground",
        "LineItems": [
            {
                "MfgCOfCRequired": False,
                "CustomerLineItemId": "1",
                "ProductDescription": proposal["component_name"],
                "DigiKeyPartNumber": proposal["part_number"],
                "ManufacturerPartNumber": proposal["manufacturer_part_number"],
                "RequestedQuantity": proposal["quantity"],
                "UnitPrice": proposal["unit_price"],
            }
        ],
        "OrderNotes": ["AP2-authorized academic sandbox order"],
        "PackagingPreference": "CT",
        "Taxable": True,
    }


async def place_order(
    proposal_id: str,
    approval_token: str,
    idempotency_key: str,
    payment_credential_id: str,
) -> dict:
    """Validate approval/AP2 and submit exactly once to DigiKey sandbox Ordering."""

    if not settings.digikey_order_sandbox:
        raise PurchaseError("Production DigiKey ordering is disabled.")
    db = await get_db()
    previous = await db.get_digikey_order_by_key(idempotency_key)
    if previous:
        return {
            "success": previous["status"] not in {"failed"},
            "order_id": previous["order_id"],
            "sales_order_id": previous["sales_order_id"],
            "status": previous["status"],
            "idempotent_replay": True,
        }
    proposal = await db.get_digikey_proposal(proposal_id)
    if proposal is None:
        raise PurchaseError(f"Unknown DigiKey proposal: {proposal_id}")
    if proposal["status"] != "pending":
        raise PurchaseError(f"Proposal {proposal_id} is {proposal['status']}.")
    expires = datetime.strptime(proposal["expires_at"], _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    if _now() > expires:
        await db.update_digikey_proposal(proposal_id, "expired")
        raise PurchaseError(f"Proposal {proposal_id} has expired.")
    if not security.verify_proposal(
        proposal_id, proposal["total"], proposal["expires_at"], approval_token
    ):
        raise PurchaseError("Invalid or mismatched human-approval token.")

    try:
        token = await access_token()
    except OAuthError as error:
        raise PurchaseError(str(error)) from error
    mandates = json.loads(proposal["mandate_json"])
    if not payment_credential_id.startswith("cp_test_"):
        raise PurchaseError("A tokenized sandbox payment credential is required.")
    mandates["payment_mandate_sdjwt"] = _payment_mandate(
        proposal, mandates, payment_credential_id
    )
    order_id = f"DKS-{secrets.token_hex(6)}"
    await db.insert_digikey_order(
        order_id=order_id,
        proposal_id=proposal_id,
        idempotency_key=idempotency_key,
        sales_order_id=None,
        status="submitting",
        mandate_json=json.dumps(mandates),
        response_json=None,
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "X-DIGIKEY-Client-Id": settings.digikey_order_client_id,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.digikey_timeout_seconds) as client:
            response = await client.post(
                "https://sandbox-api.digikey.com/Ordering/v3/Orders",
                headers=headers,
                json=_order_body(proposal, order_id),
            )
            response.raise_for_status()
            response_data = response.json()
    except httpx.HTTPStatusError as error:
        await db.update_digikey_order(order_id, "failed", None, "{}")
        raise PurchaseError(
            f"DigiKey sandbox order failed with HTTP {error.response.status_code}."
        ) from error
    except (httpx.HTTPError, ValueError) as error:
        await db.update_digikey_order(order_id, "failed", None, "{}")
        raise PurchaseError("DigiKey sandbox ordering is currently unavailable.") from error

    sales_order_id = response_data.get("SalesOrderId")
    status = "received" if str(sales_order_id) == "-1" else "submitted"
    await db.update_digikey_order(
        order_id, status, str(sales_order_id) if sales_order_id is not None else None,
        json.dumps(response_data),
    )
    await db.update_digikey_proposal(proposal_id, "ordered")
    return {
        "success": True,
        "order_id": order_id,
        "sales_order_id": sales_order_id,
        "status": status,
        "sandbox": True,
        "idempotent_replay": False,
        "ap2": {
            "checkout_mandate_verified": True,
            "payment_mandate_signed": True,
            "human_approved": True,
        },
    }


async def order_status(order_id: str) -> dict:
    """Return the locally recorded sandbox submission and DigiKey reference."""

    db = await get_db()
    order = await db.get_digikey_order(order_id)
    if order is None:
        return {"found": False, "error": f"Unknown DigiKey sandbox order: {order_id}"}
    return {
        "found": True,
        "order_id": order["order_id"],
        "proposal_id": order["proposal_id"],
        "sales_order_id": order["sales_order_id"],
        "status": order["status"],
        "sandbox": True,
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
    }
