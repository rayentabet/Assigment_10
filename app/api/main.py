"""FastAPI application exposing the multi-agent chat service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.api.schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    ThreadHistoryResponse,
    ThreadListResponse,
    ThreadResponse,
)
from app.chat_service import (
    close_chat_service,
    delete_thread,
    get_artifact_path,
    get_thread_artifact_ids,
    get_thread_history,
    initialize_chat_service,
    list_threads,
    resume_thread,
    send_message,
)
from app.chat_service import create_thread as register_thread


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Keep the SQLite checkpointer open for the API process lifetime."""

    await initialize_chat_service()
    try:
        yield
    finally:
        await close_chat_service()

app = FastAPI(
    title="Robotics Multi-Agent API",
    version="0.1.0",
    description="Thread-based HTTP API for the LangGraph robotics agent.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report that the API process is available."""

    return {"status": "ok"}


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

    messages = await get_thread_history(thread_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found.",
        )
    artifact_ids = await get_thread_artifact_ids(thread_id)
    return ThreadHistoryResponse(
        thread_id=thread_id,
        messages=messages,
        image_urls=[f"/artifacts/{artifact_id}" for artifact_id in artifact_ids],
    )


@app.get("/artifacts/{artifact_id}", response_class=FileResponse)
async def get_artifact(artifact_id: str):
    """Serve a registered image without exposing its filesystem path."""

    path = await get_artifact_path(artifact_id)
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The agent could not process the message.",
        ) from exc
    return await _to_chat_response(result)


@app.post("/threads/{thread_id}/resume", response_model=ChatResponse)
async def resume_message(
    thread_id: str, decision: ApprovalDecision
) -> ChatResponse:
    """Approve or reject the action currently paused on a thread."""

    try:
        result = await resume_thread(thread_id, decision.approved)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The thread has no resumable approval request.",
        ) from exc
    return await _to_chat_response(result)


async def _to_chat_response(result: dict) -> ChatResponse:
    """Convert internal graph state into a stable public response."""

    interrupts = result.get("__interrupt__") or []
    thread_id = result["thread_id"]
    artifact_ids = await get_thread_artifact_ids(thread_id)
    image_urls = [f"/artifacts/{artifact_id}" for artifact_id in artifact_ids]
    if interrupts:
        payload = getattr(interrupts[0], "value", interrupts[0])
        return ChatResponse(
            thread_id=thread_id,
            status="approval_required",
            approval=ApprovalRequest.model_validate(payload),
            image_urls=image_urls,
        )

    return ChatResponse(
        thread_id=thread_id,
        status="completed",
        answer=result.get("final_answer") or "No answer was produced.",
        image_urls=image_urls,
    )
