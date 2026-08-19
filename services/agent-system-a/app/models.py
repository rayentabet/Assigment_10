"""Chat model construction, with an optional OpenRouter fallback for every role.

Every specialist, the supervisor, the guardrail safety model, and the chat
title model are built through this module instead of instantiating
ChatGroq/ChatGoogleGenerativeAI directly, so all of them get the same
fallback behavior: if OPENROUTER_API_KEY is set, a primary provider failure
retries once against a single fallback model on OpenRouter's OpenAI-compatible
endpoint before giving up. Left unset (the default), no fallback is attached
and a primary failure surfaces directly.
"""

import logging
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _warn_fallback_disabled() -> None:
    """Warn once per process that no fallback provider is configured."""

    logger.warning(
        "OPENROUTER_API_KEY is not set, so model fallbacks are disabled: a "
        "primary provider failure (rate limit, outage) now fails the request "
        "outright."
    )


def _with_fallback(primary: BaseChatModel) -> BaseChatModel:
    """Attach the OpenRouter fallback runnable, tried only if `primary` raises.

    Without a key the fallback can only ever answer 401, which buys nothing but
    an extra round trip on every failure, so the primary is returned unwrapped
    instead. `.with_fallbacks()` re-raises the primary's error when every
    runnable fails, so the real cause still surfaces either way.
    """

    if not settings.openrouter_api_key:
        _warn_fallback_disabled()
        return primary

    from langchain_openai import ChatOpenAI

    fallback = ChatOpenAI(
        model=settings.fallback_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=0,
    )
    return primary.with_fallbacks([fallback])


def supervisor_model() -> BaseChatModel:
    """Routing model used by the supervisor node."""

    return _with_fallback(ChatGroq(model=settings.supervisor_model, temperature=0))


def guardrail_model() -> BaseChatModel:
    """Safety model backing the NeMo input/output rails."""

    return _with_fallback(ChatGroq(model=settings.guardrail_model, temperature=0))


def rag_model() -> BaseChatModel:
    """Model used by the documentation RAG specialist."""

    return _with_fallback(ChatGoogleGenerativeAI(model=settings.rag_model, temperature=0))


def code_model() -> BaseChatModel:
    """Model used by the coding specialist."""

    return _with_fallback(ChatGroq(model=settings.code_model, temperature=0))


def wiring_model() -> BaseChatModel:
    """Model used by the wiring and pin-management specialist."""

    return _with_fallback(ChatGroq(model=settings.wiring_model, temperature=0))


def visualization_model() -> BaseChatModel:
    """Model used by the robot visualization specialist."""

    return _with_fallback(ChatGoogleGenerativeAI(model=settings.visualization_model, temperature=0))


def title_model() -> BaseChatModel:
    """Small model used to generate a short chat title after the first turn."""

    return _with_fallback(ChatGroq(model=settings.title_model, temperature=0))
