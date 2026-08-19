import pytest_asyncio

from component_manager.config import settings
from component_manager.db import reset_db


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path, monkeypatch):
    """Give every test a fresh database and a fixed HMAC secret."""

    monkeypatch.setattr(settings, "database_path", tmp_path / "component_manager.sqlite")
    monkeypatch.setattr(settings, "approval_token_secret", "test-secret")
    await reset_db()
    yield
    await reset_db()
