"""NeMo input and output guardrails around the LangGraph workflow."""

import re
from functools import lru_cache
from pathlib import Path

from langchain_groq import ChatGroq
from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import RailType

from app.config import settings

GUARDRAILS_CONFIG = Path(__file__).parents[1] / "guardrails"
BLOCKED_MESSAGE = "I can't help with that request."

SENSITIVE_PATTERNS = {
    "EMAIL_ADDRESS": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "CREDIT_CARD": r"\b(?:\d[ -]*?){13,19}\b",
    "US_SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "PHONE_NUMBER": r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)",
}


def mask_text(text: str, entities=SENSITIVE_PATTERNS) -> str:
    """Mask sensitive values before any LLM receives the text."""

    for entity in entities:
        if pattern := SENSITIVE_PATTERNS.get(entity):
            text = re.sub(pattern, f"<{entity}>", text)
    return text


async def mask_sensitive_data(source: str, text: str, config) -> str:
    """Mask configured sensitive values without requiring a large NLP model."""

    options = getattr(config.rails.config.sensitive_data_detection, source)
    return mask_text(text, options.entities)


@lru_cache(maxsize=1)
def get_guardrails() -> LLMRails:
    """Load the NeMo configuration once and reuse it."""

    config = RailsConfig.from_path(str(GUARDRAILS_CONFIG))
    safety_model = ChatGroq(model=settings.guardrail_model, temperature=0)
    rails = LLMRails(config=config, llm=safety_model)
    rails.register_action(mask_sensitive_data, name="mask_sensitive_data")
    return rails


def _is_blocked(result) -> bool:
    """Support both enum and string statuses across NeMo versions."""

    status = getattr(result.status, "value", result.status)
    return str(status).lower() == "blocked"


async def check_input(user_input: str) -> str | None:
    """Reject prompt attacks and return input with sensitive data masked."""

    masked_input = mask_text(user_input)
    result = await get_guardrails().check_async(
        [{"role": "user", "content": masked_input}],
        rail_types=[RailType.INPUT],
    )
    if _is_blocked(result):
        return None
    return result.content or masked_input


async def check_output(
    user_input: str, answer: str, evidence: list[str]
) -> str | None:
    """Reject unsafe output and mask PII."""

    messages = [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    result = await get_guardrails().check_async(
        messages, rail_types=[RailType.OUTPUT]
    )
    if _is_blocked(result):
        return None
    return result.content or answer
