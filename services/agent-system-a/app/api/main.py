"""FastAPI application exposing the multi-agent chat service."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

from app.api.schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    PaymentConfig,
    PaymentCredential,
    PurchaseProposal,
    SandboxCardRequest,
    ThreadHistoryResponse,
    ThreadListResponse,
    ThreadResponse,
    TranscriptionResponse,
)
from app.chat_service import create_thread as register_thread
from app.chat_service import (
    delete_thread,
    get_history,
    get_project,
    get_purchase,
    get_wiring,
    initialize,
    list_artifacts,
    list_threads,
    resume_thread,
    send_message,
    shutdown,
    stream_resume_thread,
    stream_send_message,
)
from app.chat_service import (
    get_artifact as find_artifact,
)
from app.config import settings
from app.payment_vault import CredentialError, forget, provider, public, tokenize
from app.payment_vault import clear as clear_payment_vault
from app.transcription import transcribe_audio


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Keep the SQLite checkpointer open for the API process lifetime."""

    await initialize()
    try:
        yield
    finally:
        clear_payment_vault()
        await shutdown()


logger = logging.getLogger(__name__)

app = FastAPI(
    title="Robotics Multi-Agent API",
    version="0.1.0",
    description="Thread-based HTTP API for the LangGraph robotics agent.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the API process is available."""

    return {"status": "ok"}


def _component_manager_rest_client() -> httpx.AsyncClient:
    """A client for System B's REST API, used only by the DigiKey OAuth proxy below."""

    return httpx.AsyncClient(base_url=settings.component_manager_rest_url, timeout=30.0)


@app.get("/auth/digikey/start", response_class=RedirectResponse)
async def start_digikey_oauth() -> RedirectResponse:
    """Redirect the user's browser to DigiKey sandbox login and consent."""

    try:
        async with _component_manager_rest_client() as client:
            response = await client.get("/oauth/digikey/authorize")
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Component Manager is unreachable.") from error
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(status_code=503, detail=response.json().get("detail", response.text))
    return RedirectResponse(url=response.json()["url"], status_code=status.HTTP_302_FOUND)


@app.get("/auth/digikey/callback", response_class=HTMLResponse)
async def finish_digikey_oauth(
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Validate DigiKey's callback and store encrypted, rotating OAuth tokens."""

    if error:
        return HTMLResponse(
            "<h1>DigiKey connection declined</h1><p>You may close this tab.</p>",
            status_code=400,
        )
    if not code or not state_value:
        raise HTTPException(status_code=400, detail="Missing DigiKey OAuth code or state.")
    try:
        async with _component_manager_rest_client() as client:
            response = await client.post(
                "/oauth/digikey/callback", json={"code": code, "state": state_value}
            )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Component Manager is unreachable.") from error
    if response.status_code != status.HTTP_204_NO_CONTENT:
        raise HTTPException(status_code=400, detail=response.json().get("detail", response.text))
    return HTMLResponse(
        "<h1>DigiKey sandbox connected</h1>"
        "<p>The tokens were encrypted on the backend. You may close this tab and return "
        "to the Robotics Assistant.</p>"
    )


@app.get("/auth/digikey/status")
async def digikey_oauth_status() -> dict:
    """Tell React whether a sandbox account is connected without exposing tokens."""

    async with _component_manager_rest_client() as client:
        response = await client.get("/oauth/digikey/status")
    response.raise_for_status()
    return response.json()


@app.delete("/auth/digikey/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_digikey() -> Response:
    """Delete locally stored DigiKey OAuth tokens."""

    async with _component_manager_rest_client() as client:
        response = await client.delete("/oauth/digikey/connection")
    response.raise_for_status()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def tokenize_sandbox_card(request: SandboxCardRequest) -> PaymentCredential:
    """Exchange AP2 test-card fields for an ephemeral, proposal-bound reference."""

    try:
        credential = tokenize(
            request.card_number,
            request.expiry,
            request.cvv,
        )
    except CredentialError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return PaymentCredential.model_validate(credential)


if settings.payment_provider == "sandbox":
    app.add_api_route(
        "/payments/sandbox/tokenize",
        tokenize_sandbox_card,
        methods=["POST"],
        response_model=PaymentCredential,
    )


@app.get("/payments/config", response_model=PaymentConfig)
async def payment_config() -> PaymentConfig:
    """Expose only browser-safe provider configuration."""
    return PaymentConfig(
        provider=settings.payment_provider,
    )


@app.post("/payments/lithic/methods", response_model=PaymentCredential)
async def create_lithic_method() -> PaymentCredential:
    """Create a safe local handle; the Lithic card is issued only after AP2 approval."""
    if settings.payment_provider != "lithic":
        raise HTTPException(status_code=404, detail="Lithic payments are not enabled.")
    method = provider.create_payment_method()
    return PaymentCredential.model_validate(public(method))


@app.delete(
    "/payments/sandbox/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def forget_sandbox_card(credential_id: str) -> Response:
    """Forget a reusable in-memory sandbox payment method."""

    forget(credential_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/threads",
    response_model=ThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread() -> ThreadResponse:
    """Create a client-visible conversation identifier."""

    thread_id = str(uuid4())
    await register_thread(thread_id)
    return ThreadResponse(thread_id=thread_id)


@app.get("/threads", response_model=ThreadListResponse)
async def get_threads() -> ThreadListResponse:
    """List recent conversations for the frontend selector."""

    return ThreadListResponse(threads=await list_threads())


@app.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_thread(thread_id: str) -> Response:
    """Permanently delete a conversation and its saved graph state."""

    if not await delete_thread(thread_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/threads/{thread_id}/messages",
    response_model=ThreadHistoryResponse,
)
async def get_messages(thread_id: str) -> ThreadHistoryResponse:
    """Return public user and assistant messages in chronological order."""

    messages = await get_history(thread_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )
    artifact_ids = await list_artifacts(thread_id)
    wiring_plan = await get_wiring(thread_id)
    purchase_reference = await get_purchase(thread_id)
    project = await get_project(thread_id) or {}
    return ThreadHistoryResponse(
        thread_id=thread_id,
        messages=messages,
        image_urls=[f"/artifacts/{artifact_id}" for artifact_id in artifact_ids],
        wiring_plan=wiring_plan,
        purchase_reference=purchase_reference,
        product_cards=project.get("product_cards", []),
    )


@app.post("/threads/{thread_id}/transcribe", response_model=TranscriptionResponse)
async def transcribe_message(
    thread_id: str, audio: Annotated[UploadFile, File()]
) -> TranscriptionResponse:
    """Transcribe a voice message with the local Whisper model.

    Returns text only; the caller sends it to POST /threads/{id}/messages
    like any typed message. Transcription itself never touches the graph.
    """

    if await get_history(thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )

    audio_bytes = await audio.read()
    try:
        text = await transcribe_audio(audio_bytes)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except Exception as exc:
        logger.exception("Transcription failed for thread %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription failed.",
        ) from exc

    return TranscriptionResponse(text=text)


@app.get("/artifacts/{artifact_id}", response_class=FileResponse)
async def get_artifact(artifact_id: str):
    """Serve a registered image without exposing its filesystem path."""

    path = await find_artifact(artifact_id)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found.",
        )
    return FileResponse(path)


@app.post("/threads/{thread_id}/messages", response_model=ChatResponse)
async def post_message(thread_id: str, request: ChatRequest) -> ChatResponse:
    """Send a user message to a new or existing graph thread."""

    try:
        result = await send_message(request.message.strip(), thread_id=thread_id)
    except Exception as exc:
        logger.exception("send_message failed for thread %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The agent could not process the message.",
        ) from exc
    return await chat_response(result)


@app.post("/threads/{thread_id}/resume", response_model=ChatResponse)
async def resume_message(thread_id: str, decision: ApprovalDecision) -> ChatResponse:
    """Approve or reject the action currently paused on a thread."""

    try:
        result = await resume_thread(
            thread_id,
            decision.approved,
            payment_method_id=decision.payment_method_id,
        )
    except Exception as exc:
        logger.exception("resume_thread failed for thread %s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The thread has no resumable approval request.",
        ) from exc
    return await chat_response(result)


STREAM_UPDATE_FIELDS = {
    "tool_trace",
    "route_history",
    "next_agent",
    "completed_tasks",
    "project",
    "final_answer",
    "image_paths",
    "iteration_count",
    "input_blocked",
}


async def _sse_frame(item: dict) -> str:
    """Format one streamed chat_service item as an SSE `data:` line.

    `item["kind"]` is `"chunk"` (a raw LangGraph node update, or the
    standalone `{"__interrupt__": ...}` marker), `"done"` (a complete turn,
    shaped exactly like `send_message`/`resume_thread`'s return value), or
    `"error"` (an unhandled exception from the graph run itself).
    """

    kind, payload = item["kind"], item["payload"]

    if kind == "chunk":
        if "__interrupt__" in payload:
            # The terminal "done" frame already carries status:
            # "approval_required" with the full approval/proposal payload;
            # a bare interrupt marker has nothing new to tell the client.
            return ""
        node, update = next(iter(payload.items()))
        update = update or {}
        frame = {
            "type": "node",
            "node": node,
            "update": {key: update[key] for key in STREAM_UPDATE_FIELDS if key in update},
        }
    elif kind == "done":
        response = await chat_response(payload)
        frame = {"type": "done", **response.model_dump(mode="json")}
    else:
        # chat_service already logged the exception with its traceback;
        # the client only needs to know the turn failed.
        frame = {"type": "error", "message": "The agent could not process the message."}

    return f"data: {json.dumps(frame)}\n\n"


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/threads/{thread_id}/messages/stream")
async def post_message_stream(thread_id: str, request: ChatRequest) -> StreamingResponse:
    """Stream one turn's per-node progress, then its final result, over SSE."""

    async def event_generator() -> AsyncIterator[str]:
        async for item in stream_send_message(request.message.strip(), thread_id=thread_id):
            frame = await _sse_frame(item)
            if frame:
                yield frame

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/threads/{thread_id}/resume/stream")
async def resume_message_stream(thread_id: str, decision: ApprovalDecision) -> StreamingResponse:
    """Stream a paused thread's resumption the same way `post_message_stream` does."""

    async def event_generator() -> AsyncIterator[str]:
        async for item in stream_resume_thread(
            thread_id, decision.approved, payment_method_id=decision.payment_method_id
        ):
            frame = await _sse_frame(item)
            if frame:
                yield frame

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


async def chat_response(result: dict) -> ChatResponse:
    """Convert internal graph state into a stable public response."""

    interrupts = result.get("__interrupt__") or []
    thread_id = result["thread_id"]
    artifact_ids = await list_artifacts(thread_id)
    image_urls = [f"/artifacts/{artifact_id}" for artifact_id in artifact_ids]
    project = result.get("project", {})
    wiring_plan = project.get("wiring")
    purchase = project.get("purchase")
    purchase_reference = purchase if purchase and purchase.get("order_id") else None
    product_cards = project.get("product_cards", [])
    tool_trace = result.get("tool_trace", [])
    route_history = result.get("route_history", [])
    if interrupts:
        payload = getattr(interrupts[0], "value", interrupts[0])
        if payload.get("action") == "place_order":
            return ChatResponse(
                thread_id=thread_id,
                status="approval_required",
                purchase_proposal=PurchaseProposal.model_validate(payload),
                image_urls=image_urls,
                wiring_plan=wiring_plan,
                purchase_reference=purchase_reference,
                product_cards=product_cards,
                tool_trace=tool_trace,
                route_history=route_history,
            )
        return ChatResponse(
            thread_id=thread_id,
            status="approval_required",
            approval=ApprovalRequest.model_validate(payload),
            image_urls=image_urls,
            wiring_plan=wiring_plan,
            purchase_reference=purchase_reference,
            product_cards=product_cards,
            tool_trace=tool_trace,
            route_history=route_history,
        )

    return ChatResponse(
        thread_id=thread_id,
        status="completed",
        answer=result.get("final_answer") or "No answer was produced.",
        image_urls=image_urls,
        wiring_plan=wiring_plan,
        purchase_reference=purchase_reference,
        product_cards=product_cards,
        tool_trace=tool_trace,
        route_history=route_history,
    )
