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
    def message_must_not_be_blank(cls, value: str) -> str:
        """Reject whitespace-only messages and normalize surrounding spaces."""

        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ApprovalDecision(BaseModel):
    """Human decision for a paused agent action."""

    approved: bool


class ApprovalRequest(BaseModel):
    """Description of an action waiting for human approval."""

    question: str
    action: str
    task: str
    reason: str


class ChatResponse(BaseModel):
    """Normalized result returned by a graph invocation."""

    thread_id: str
    status: Literal["completed", "approval_required"]
    answer: str | None = None
    approval: ApprovalRequest | None = None
    image_urls: list[str] = Field(default_factory=list)


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


class ThreadSummary(BaseModel):
    """One selectable conversation in the chat sidebar."""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadListResponse(BaseModel):
    """Recent conversations ordered by latest activity."""

    threads: list[ThreadSummary]
