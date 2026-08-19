"""Model construction and provider-fallback wiring."""

import pytest
from langchain_core.runnables import RunnableWithFallbacks
from pydantic import BaseModel

from app import models
from app.config import settings


@pytest.fixture(autouse=True)
def _provider_keys(monkeypatch):
    """Give every provider a key so models construct without real credentials."""

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    models._warn_fallback_disabled.cache_clear()


def test_no_fallback_is_attached_without_an_openrouter_key(monkeypatch, caplog):
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    model = models.wiring_model()

    assert not isinstance(model, RunnableWithFallbacks)
    assert "OPENROUTER_API_KEY is not set" in caplog.text


def test_fallback_is_attached_when_a_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")

    model = models.wiring_model()

    assert isinstance(model, RunnableWithFallbacks)
    assert len(model.fallbacks) == 1


def test_fallback_survives_tool_binding(monkeypatch):
    """create_agent() binds tools to the model; that must not drop the fallback."""

    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")

    bound = models.wiring_model().bind_tools([])

    assert isinstance(bound, RunnableWithFallbacks)
    assert len(bound.fallbacks) == 1


def test_fallback_survives_structured_output(monkeypatch):
    """The supervisor routes through with_structured_output(); same requirement."""

    class Route(BaseModel):
        next_agent: str

    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")

    router = models.supervisor_model().with_structured_output(
        Route, method="json_schema", strict=True
    )

    assert isinstance(router, RunnableWithFallbacks)
    assert len(router.fallbacks) == 1
