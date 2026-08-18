"""A2A client connecting System A to the Component Manager (System B)."""

import asyncio
import time
from typing import Any

import httpx
from a2a.client import Client, ClientConfig, create_client
from a2a.helpers.proto_helpers import get_data_parts, get_text_parts, new_text_message
from a2a.types import a2a_pb2

from app.config import settings

_client: Client | None = None
_client_lock = asyncio.Lock()

_FAILURE_STATES = {
    a2a_pb2.TaskState.TASK_STATE_FAILED,
    a2a_pb2.TaskState.TASK_STATE_CANCELED,
    a2a_pb2.TaskState.TASK_STATE_REJECTED,
}
_SETTLED_STATES = _FAILURE_STATES | {a2a_pb2.TaskState.TASK_STATE_COMPLETED}
_POLL_INTERVAL_SECONDS = 1.0


async def _get_client() -> Client:
    """Resolve the Component Manager's Agent Card once and reuse the client.

    The default httpx client's timeout is too short for a real turn where
    System B's model makes two or three sequential tool calls plus its own
    generation latency; a real run against gemini-3.1-flash-lite making two
    tool calls timed out at the client's default before completing.
    """

    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is not None:
            return _client
        httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(settings.a2a_timeout_seconds))
        _client = await create_client(
            settings.component_manager_a2a_url,
            client_config=ClientConfig(streaming=False, httpx_client=httpx_client),
        )
        return _client


def _text_of(parts: Any) -> str:
    return "\n".join(get_text_parts(parts))


def _parse_task(task: Any) -> dict:
    """Extract every tool call/result System B's model made, plus its final answer."""

    tool_calls: list[dict] = []
    tool_results: list[dict] = []
    for message in task.history:
        for part in get_data_parts(message.parts):
            if not isinstance(part, dict):
                continue
            if "args" in part:
                tool_calls.append(
                    {
                        "tool": part.get("name"),
                        "id": part.get("id"),
                        "arguments": part.get("args", {}),
                    }
                )
            elif "response" in part:
                tool_results.append(
                    {
                        "tool": part.get("name"),
                        "id": part.get("id"),
                        "result": part.get("response", {}),
                    }
                )

    answer = ""
    if task.artifacts:
        answer = _text_of(task.artifacts[-1].parts)
    if not answer and task.status.message and task.status.message.parts:
        answer = _text_of(task.status.message.parts)
    if not answer:
        for message in reversed(task.history):
            text = _text_of(message.parts)
            if text:
                answer = text
                break

    return {"answer": answer, "tool_calls": tool_calls, "tool_results": tool_results}


async def _await_task(client: Client, task: Any, deadline: float) -> Any:
    """Poll a non-terminal task until it settles or the deadline passes."""

    while task.status.state not in _SETTLED_STATES:
        if time.monotonic() >= deadline:
            raise TimeoutError("Component Manager task did not complete in time")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        task = await client.get_task(a2a_pb2.GetTaskRequest(id=task.id))
    return task


async def _send_once(task_text: str, deadline: float) -> dict:
    """Send one plain-text task and return the parsed result, or raise on failure."""

    client = await _get_client()
    message = new_text_message(task_text)
    request = a2a_pb2.SendMessageRequest(message=message)

    task = None
    async for response in client.send_message(request):
        kind = response.WhichOneof("payload")
        if kind == "message":
            return {
                "answer": _text_of(response.message.parts),
                "tool_calls": [],
                "tool_results": [],
            }
        if kind == "task":
            task = response.task
        break  # streaming is disabled: exactly one response is expected

    if task is None:
        raise RuntimeError("Component Manager returned an empty response")

    task = await _await_task(client, task, deadline)
    if task.status.state in _FAILURE_STATES:
        detail = _text_of(task.status.message.parts) if task.status.message.parts else None
        raise RuntimeError(detail or f"Component Manager task {task.status.state}")

    return _parse_task(task)


async def contact_manager(task_text: str) -> dict:
    """Relay one task to System B's agent, with a timeout and bounded retries.

    Returns {"answer": str, "tool_calls": [...], "tool_results": [...]} on
    success, or {"error": str} after exhausting retries. tool_calls/results
    mirror exactly what System B's own model decided to do — System A never
    invents or second-guesses them.
    """

    last_error: Exception | None = None
    for _ in range(settings.a2a_max_retries + 1):
        deadline = time.monotonic() + settings.a2a_timeout_seconds
        try:
            return await asyncio.wait_for(
                _send_once(task_text, deadline), timeout=settings.a2a_timeout_seconds
            )
        except Exception as error:  # noqa: BLE001 - always degrade to a structured error
            last_error = error
    return {"error": f"Component Manager call failed: {last_error}"}


def last_result(result: dict, tool_name: str) -> dict | None:
    """Return the most recent result System B's model got from one named tool."""

    matches = [
        entry["result"] for entry in result.get("tool_results", []) if entry["tool"] == tool_name
    ]
    return matches[-1] if matches else None


def last_argument(result: dict, tool_name: str, argument: str) -> Any | None:
    """Return the most recent argument value System B's model passed to one named tool."""

    matches = [
        entry["arguments"].get(argument)
        for entry in result.get("tool_calls", [])
        if entry["tool"] == tool_name
    ]
    return matches[-1] if matches else None
