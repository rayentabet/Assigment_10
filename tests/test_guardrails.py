from types import SimpleNamespace

import pytest

from app import guardrails


def masking_config(entities: list[str]):
    options = SimpleNamespace(entities=entities)
    detection = SimpleNamespace(input=options, output=options)
    return SimpleNamespace(
        rails=SimpleNamespace(config=SimpleNamespace(sensitive_data_detection=detection))
    )


class FakeRails:
    def __init__(self, status: str, content: str):
        self.result = SimpleNamespace(status=status, content=content)
        self.calls = []

    async def check_async(self, messages, rail_types):
        self.calls.append((messages, rail_types))
        return self.result


@pytest.mark.asyncio
async def test_input_guardrail_returns_masked_content(monkeypatch) -> None:
    rails = FakeRails("passed", "")
    monkeypatch.setattr(guardrails, "get_guardrails", lambda: rails)

    assert await guardrails.check_input("Email: me@example.com") == ("Email: <EMAIL_ADDRESS>")
    assert rails.calls[0][0][0]["content"] == "Email: <EMAIL_ADDRESS>"


@pytest.mark.asyncio
async def test_regex_masks_configured_sensitive_data() -> None:
    text = (
        "Email me@example.com, call +1 (212) 555-1234, use card "
        "4111 1111 1111 1111, SSN 123-45-6789, or IP 192.168.1.1."
    )
    config = masking_config(list(guardrails.SENSITIVE_PATTERNS))

    masked = await guardrails.mask_data("input", text, config)

    assert "me@example.com" not in masked
    assert "212" not in masked
    assert "4111" not in masked
    assert "123-45-6789" not in masked
    assert "192.168.1.1" not in masked
