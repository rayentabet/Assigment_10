"""Request and response models for the chat API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ThreadResponse(BaseModel):
    """Identifier for a conversation thread."""

    thread_id: str


class ChatRequest(BaseModel):
    """A user message sent to an existing thread."""

    message: str = Field(min_length=1, max_length=20_000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Reject whitespace-only messages and normalize surrounding spaces."""

        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ApprovalDecision(BaseModel):
    """Human decision for a paused agent action."""

    approved: bool
    payment_credential_id: str | None = Field(default=None, max_length=128)


class SandboxCardRequest(BaseModel):
    """Sensitive test fields accepted only by the deterministic credential route."""

    card_number: str = Field(min_length=12, max_length=32)
    expiry: str = Field(min_length=4, max_length=7)
    cvv: str = Field(min_length=3, max_length=4)


class PaymentCredential(BaseModel):
    """Non-sensitive tokenization result safe to display outside the vault."""

    credential_id: str
    brand: str
    last4: str
    expires_at: int
    sandbox: bool


class ApprovalRequest(BaseModel):
    """Description of an action waiting for human approval."""

    question: str
    action: str
    task: str
    reason: str


class WiringPlan(BaseModel):
    """Structured pin allocation produced by the wiring agent."""

    board: str
    valid: bool
    components: list[dict] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    table_markdown: str = ""


class PurchaseProposal(BaseModel):
    """Immutable purchase terms awaiting human approval.

    Distinct from ApprovalRequest: a purchase proposal pauses mid-flow, after
    the Component Manager has already produced binding-looking terms (price,
    total, expiry), rather than gating a specialist before it starts.
    """

    question: str
    proposal_id: str
    component_id: str
    component_name: str | None = None
    quantity: int
    supplier_name: str | None = None
    unit_price: float
    currency: str
    fees: float | None = None
    total: float
    delivery_estimate_days: int | None = None
    expires_at: str


class PurchaseReference(BaseModel):
    """Thin pointer to a submitted order; financial detail stays in System B."""

    proposal_id: str | None = None
    order_id: str | None = None
    status: str | None = None


class ProductCard(BaseModel):
    """Public, read-only supplier offer returned by DigiKey search."""

    supplier: str
    digikey_part_number: str | None = None
    manufacturer_part_number: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    quantity_available: int
    requested_quantity: int
    unit_price: float | None = None
    total_price: float | None = None
    currency: str
    product_url: str | None = None
    image_url: str | None = None
    datasheet_url: str | None = None


class ToolTraceEntry(BaseModel):
    """One tool call or tool result from the turn that just completed.

    A post-hoc substitute for live SSE tool-progress events (the proposal's
    §8 describes a streamed activity feed; this app uses request/response
    instead), so this only reflects the most recent turn, not full history.
    """

    agent: str
    event: Literal["call", "result"]
    tool: str
    arguments: dict | None = None
    content: str | None = None
    tool_call_id: str | None = None


class ChatResponse(BaseModel):
    """Normalized result returned by a graph invocation."""

    thread_id: str
    status: Literal["completed", "approval_required"]
    answer: str | None = None
    approval: ApprovalRequest | None = None
    purchase_proposal: PurchaseProposal | None = None
    image_urls: list[str] = Field(default_factory=list)
    wiring_plan: WiringPlan | None = None
    purchase_reference: PurchaseReference | None = None
    product_cards: list[ProductCard] = Field(default_factory=list)
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    route_history: list[str] = Field(default_factory=list)


class HistoryMessage(BaseModel):
    """One public user or assistant message saved for a thread."""

    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ThreadHistoryResponse(BaseModel):
    """Ordered public chat history for a thread."""

    thread_id: str
    messages: list[HistoryMessage]
    image_urls: list[str] = Field(default_factory=list)
    wiring_plan: WiringPlan | None = None
    purchase_reference: PurchaseReference | None = None
    product_cards: list[ProductCard] = Field(default_factory=list)


class ThreadSummary(BaseModel):
    """One selectable conversation in the chat sidebar."""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadListResponse(BaseModel):
    """Recent conversations ordered by latest activity."""

    threads: list[ThreadSummary]


class TranscriptionResponse(BaseModel):
    """Text produced by the local Whisper model for one audio clip."""

    text: str
