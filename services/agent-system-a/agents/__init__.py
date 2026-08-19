"""Specialist agent nodes."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

T = TypeVar("T")


def cached_agent(factory: Callable[[], Awaitable[T]]) -> Callable[[], Awaitable[T]]:
    """Memoize an async agent factory for the lifetime of the process.

    The first successful creation is stored and reused, so a fresh model client
    and MCP tool-discovery handshake are not opened for every graph invocation.
    Failures are not cached, so a transient outage only delays the agent instead
    of permanently poisoning it.
    """

    cache: T | None = None
    lock = asyncio.Lock()

    @wraps(factory)
    async def wrapper() -> T:
        nonlocal cache
        if cache is not None:
            return cache
        async with lock:
            if cache is not None:
                return cache
            agent = await factory()
            cache = agent
            return agent

    return wrapper
