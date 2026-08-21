"""FastAPI + SSE wrapper around System B's ADK agent.

An additive interface alongside the A2A server (`server.py`): plain REST for
manual testing/demos, with a streaming endpoint that surfaces the agent's
text and tool-call/tool-result events live instead of waiting for one final
response. Threads are backed by `SqliteSessionService`, so a `thread_id`
keeps working across restarts without needing System A to hold any state.

Run with:
    PYTHONPATH=. component_manager/.venv/bin/uvicorn component_manager.rest_api:app \
        --host 0.0.0.0 --port 8003
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.events.event import Event
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel, Field

from component_manager.agent import root_agent
from component_manager.config import settings
from component_manager.oauth import OAuthError
from component_manager.oauth import authorization_url as digikey_authorization_url
from component_manager.oauth import connection_status as digikey_connection_status
from component_manager.oauth import disconnect as digikey_disconnect
from component_manager.oauth import exchange_code as digikey_exchange_code
from component_manager.purchasing import PurchaseError
from component_manager.purchasing import place_order as place_digikey_order

_APP_NAME = "component_manager"
_USER_ID = "dev"


class ThreadResponse(BaseModel):
    """Identifier for a persisted conversation thread."""

    thread_id: str


class ThreadListResponse(BaseModel):
    """All threads persisted for this deployment."""

    threads: list[str]


class DigikeyAuthorizeResponse(BaseModel):
    """DigiKey's sandbox authorization URL for System A to redirect the browser to."""

    url: str


class DigikeyCallbackRequest(BaseModel):
    """The code/state DigiKey's OAuth callback handed to System A."""

    code: str
    state: str


class ChatMessageRequest(BaseModel):
    """A user message sent to an existing thread."""

    message: str = Field(min_length=1, max_length=20_000)


class InternalOrderRequest(BaseModel):
    """Model-free service-to-service sandbox order handoff."""

    proposal_id: str
    approval_token: str
    idempotency_key: str
    payment_reference: str


class ToolTraceEntry(BaseModel):
    """One tool call or tool result emitted while answering a message."""

    event: str
    tool: str
    arguments: dict | None = None
    content: object | None = None


class ChatAnswerResponse(BaseModel):
    """Normalized, non-streaming reply for one message."""

    thread_id: str
    answer: str
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)


class HistoryMessage(BaseModel):
    """One turn (user or agent) replayed from a persisted thread."""

    author: str
    text: str


class ThreadHistoryResponse(BaseModel):
    """Ordered turns and tool trace replayed from a persisted thread."""

    thread_id: str
    messages: list[HistoryMessage]
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)


session_service = SqliteSessionService(db_path=str(settings.session_database_path))

runner = Runner(
    app_name=_APP_NAME,
    agent=root_agent,
    session_service=session_service,
    artifact_service=InMemoryArtifactService(),
    memory_service=InMemoryMemoryService(),
    credential_service=InMemoryCredentialService(),
    auto_create_session=True,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ensure the sessions database directory exists before serving."""

    settings.session_database_path.parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Component Manager REST API",
    version="0.1.0",
    description="Standalone REST + SSE interface for System B, alongside its A2A server.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the REST process is available."""

    return {"status": "ok"}


@app.get("/oauth/digikey/authorize", response_model=DigikeyAuthorizeResponse)
async def digikey_authorize() -> DigikeyAuthorizeResponse:
    """Return DigiKey's authorization URL; System A redirects the user's browser to it."""

    try:
        url = await digikey_authorization_url()
    except OAuthError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return DigikeyAuthorizeResponse(url=url)


@app.post("/oauth/digikey/callback", status_code=status.HTTP_204_NO_CONTENT)
async def digikey_callback(request: DigikeyCallbackRequest) -> Response:
    """Validate DigiKey's callback and store encrypted, rotating OAuth tokens."""

    try:
        await digikey_exchange_code(request.code, request.state)
    except OAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/oauth/digikey/status")
async def digikey_status() -> dict:
    """Report connection metadata without exposing tokens."""

    return await digikey_connection_status()


@app.delete("/oauth/digikey/connection", status_code=status.HTTP_204_NO_CONTENT)
async def digikey_disconnect_route() -> Response:
    """Delete locally stored DigiKey OAuth tokens."""

    await digikey_disconnect()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/internal/digikey/orders")
async def submit_internal_digikey_order(request: InternalOrderRequest) -> dict:
    """Validate AP2/approval and submit without exposing payment data to ADK."""
    try:
        return await place_digikey_order(
            request.proposal_id,
            request.approval_token,
            request.idempotency_key,
            request.payment_reference,
        )
    except PurchaseError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/threads", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread() -> ThreadResponse:
    """Create a persisted conversation thread."""

    thread_id = str(uuid4())
    await session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID, session_id=thread_id)
    return ThreadResponse(thread_id=thread_id)


@app.get("/threads", response_model=ThreadListResponse)
async def list_threads() -> ThreadListResponse:
    """List persisted thread ids."""

    result = await session_service.list_sessions(app_name=_APP_NAME, user_id=_USER_ID)
    return ThreadListResponse(threads=[session.id for session in result.sessions])


def _tool_trace_from_events(events: list[Event]) -> list[ToolTraceEntry]:
    """Flatten function-call/function-response parts into a tool trace."""

    trace: list[ToolTraceEntry] = []
    for event in events:
        for part in (event.content.parts if event.content else None) or []:
            if part.function_call:
                trace.append(
                    ToolTraceEntry(
                        event="call",
                        tool=part.function_call.name or "",
                        arguments=part.function_call.args,
                    )
                )
            elif part.function_response:
                trace.append(
                    ToolTraceEntry(
                        event="result",
                        tool=part.function_response.name or "",
                        content=part.function_response.response,
                    )
                )
    return trace


def _final_text_from_events(events: list[Event]) -> str:
    """Concatenate the text parts of the last non-partial model turn."""

    for event in reversed(events):
        if event.author == _USER_ID or event.partial:
            continue
        if not event.content or not event.content.parts:
            continue
        text = "".join(part.text or "" for part in event.content.parts if part.text)
        if text:
            return text
    return ""


async def _get_session_or_404(thread_id: str):
    session = await session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=thread_id
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found.")
    return session


@app.get("/threads/{thread_id}/messages", response_model=ThreadHistoryResponse)
async def get_thread_history(thread_id: str) -> ThreadHistoryResponse:
    """Replay a persisted thread's turns and tool trace."""

    session = await _get_session_or_404(thread_id)
    messages = [
        HistoryMessage(author=event.author, text=text)
        for event in session.events
        if event.content
        for text in ["".join(part.text or "" for part in event.content.parts if part.text)]
        if text
    ]
    return ThreadHistoryResponse(
        thread_id=thread_id,
        messages=messages,
        tool_trace=_tool_trace_from_events(session.events),
    )


@app.post("/threads/{thread_id}/messages", response_model=ChatAnswerResponse)
async def post_message(thread_id: str, request: ChatMessageRequest) -> ChatAnswerResponse:
    """Send a message to a thread and return exactly one JSON reply."""

    new_message = types.Content(role="user", parts=[types.Part(text=request.message)])
    events = [
        event
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=thread_id, new_message=new_message
        )
    ]
    return ChatAnswerResponse(
        thread_id=thread_id,
        answer=_final_text_from_events(events),
        tool_trace=_tool_trace_from_events(events),
    )


def _sse_frames_for_event(event: Event) -> list[dict]:
    """Project one ADK event into zero or more small JSON envelopes.

    SSE mode yields both partial chunks and a final aggregated event per
    turn (see RunConfig.StreamingMode.SSE's docstring on the "duplicate text
    issue"). We stream only the partial text chunks for the typewriter
    effect, and only the complete (non-partial) function call/response so
    tool arguments aren't shown half-built.
    """

    frames: list[dict] = []
    for part in (event.content.parts if event.content else None) or []:
        if part.text and event.partial:
            frames.append({"type": "text", "author": event.author, "text": part.text})
        elif part.function_call and not event.partial:
            frames.append(
                {
                    "type": "tool_call",
                    "author": event.author,
                    "tool": part.function_call.name,
                    "arguments": part.function_call.args,
                }
            )
        elif part.function_response:
            frames.append(
                {
                    "type": "tool_result",
                    "author": event.author,
                    "tool": part.function_response.name,
                    "content": part.function_response.response,
                }
            )
    return frames


@app.post("/threads/{thread_id}/messages/stream")
async def stream_message(thread_id: str, request: ChatMessageRequest) -> StreamingResponse:
    """Send a message to a thread and stream text/tool events as they occur."""

    new_message = types.Content(role="user", parts=[types.Part(text=request.message)])

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in runner.run_async(
                user_id=_USER_ID,
                session_id=thread_id,
                new_message=new_message,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            ):
                for frame in _sse_frames_for_event(event):
                    yield f"data: {json.dumps(frame)}\n\n"
        except Exception as error:  # noqa: BLE001 - reported to the client, not swallowed
            yield f"data: {json.dumps({'type': 'error', 'message': str(error)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
