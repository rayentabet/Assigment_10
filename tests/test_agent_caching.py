import pytest

from agents import cached_agent


class _Agent:
    pass


@pytest.mark.asyncio
async def test_agent_factory_is_called_once_and_result_reused() -> None:
    calls = []

    @cached_agent
    async def build_agent():
        calls.append("build")
        return _Agent()

    first = await build_agent()
    second = await build_agent()

    assert first is second
    assert calls == ["build"]


@pytest.mark.asyncio
async def test_failed_creation_is_not_cached_and_is_retried() -> None:
    calls = []

    @cached_agent
    async def flaky_agent():
        calls.append("build")
        if len(calls) == 1:
            raise RuntimeError("MCP server unavailable")
        return _Agent()

    with pytest.raises(RuntimeError):
        await flaky_agent()

    agent = await flaky_agent()

    assert isinstance(agent, _Agent)
    assert calls == ["build", "build"]


@pytest.mark.asyncio
async def test_concurrent_first_calls_create_single_instance() -> None:
    import asyncio

    calls = []

    async def build_agent():
        calls.append("build")
        await asyncio.sleep(0.01)
        return _Agent()

    cached = cached_agent(build_agent)
    agents = await asyncio.gather(cached(), cached(), cached())

    assert len(calls) == 1
    assert len({id(agent) for agent in agents}) == 1
