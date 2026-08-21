"""Conversation and thread lifecycle for the multi-agent graph."""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import aiosqlite
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.config import settings
from app.graph import build_graph, new_state
from app.helpers import to_text, valid_image

logger = logging.getLogger(__name__)

_connection: aiosqlite.Connection | None = None
_checkpointer: AsyncSqliteSaver | None = None
_graph = None
_initialization_lock = asyncio.Lock()


async def initialize() -> None:
    """Open the SQLite checkpointer and compile the conversation graph."""

    global _checkpointer, _connection, _graph

    if _graph is not None:
        return

    async with _initialization_lock:
        if _graph is not None:
            return

        database_path = settings.chat_database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(database_path)
        _checkpointer = AsyncSqliteSaver(_connection)
        await _checkpointer.setup()
        await _connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_messages_thread
            ON chat_messages(thread_id, id);

            CREATE TABLE IF NOT EXISTS chat_artifacts (
                thread_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, artifact_id),
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
            );

            CREATE TABLE IF NOT EXISTS chat_wiring_plans (
                thread_id TEXT PRIMARY KEY,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
            );

            CREATE TABLE IF NOT EXISTS chat_purchase_refs (
                thread_id TEXT PRIMARY KEY,
                proposal_id TEXT,
                order_id TEXT,
                status TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
            );

            CREATE TABLE IF NOT EXISTS chat_projects (
                thread_id TEXT PRIMARY KEY,
                project_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
            );
            """
        )
        columns = await _connection.execute("PRAGMA table_info(chat_threads)")
        column_names = {row[1] for row in await columns.fetchall()}
        await columns.close()
        if "title" not in column_names:
            await _connection.execute("ALTER TABLE chat_threads ADD COLUMN title TEXT")
        await _connection.commit()
        _graph = build_graph(checkpointer=_checkpointer)


async def shutdown() -> None:
    """Close SQLite cleanly when the application shuts down."""

    global _checkpointer, _connection, _graph

    _graph = None
    _checkpointer = None
    if _connection is not None:
        await _connection.close()
        _connection = None


async def _finalize_turn(thread_id: str, result: dict) -> None:
    """Persist one completed (non-paused) turn's side effects.

    Shared by every send/resume flow, unary or streaming, so a turn is
    recorded exactly the same way regardless of how the caller reached it.
    """

    if result.get("project"):
        await save_project(thread_id, result["project"])
    if result.get("final_answer") and not result.get("__interrupt__"):
        await _save_message(thread_id, "assistant", result["final_answer"])
        if not result.get("input_blocked"):
            await _maybe_generate_title(thread_id, result["final_answer"])
        await register_artifacts(thread_id, result.get("image_paths", []))
        project = result.get("project", {})
        if project.get("wiring"):
            await save_wiring(thread_id, project["wiring"])
        if project.get("purchase"):
            await save_purchase(thread_id, project["purchase"])


async def send_message(
    user_input: str, thread_id: str | None = None, callbacks: list | None = None
) -> dict:
    """Send a message on a new or existing conversation thread.

    `callbacks` is optional and unused by the FastAPI app; the evaluation
    harness attaches a token-usage collector through it so cost tracking
    stays outside production request handling.
    """

    thread_id = thread_id or str(uuid4())
    await create_thread(thread_id)
    await _save_message(thread_id, "user", user_input)
    graph = await get_graph()
    project = await get_project(thread_id)
    config: dict = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        config["callbacks"] = callbacks
    result = await graph.ainvoke(
        new_state(user_input, thread_id=thread_id, project=project),
        config=config,
    )
    result["thread_id"] = thread_id
    await _finalize_turn(thread_id, result)
    return result


async def resume_thread(
    thread_id: str,
    approved: bool,
    payment_method_id: str | None = None,
    callbacks: list | None = None,
) -> dict:
    """Resume a paused thread with its human approval decision.

    `callbacks` is optional and unused by the FastAPI app; see `send_message`.
    """

    graph = await get_graph()
    config: dict = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        config["callbacks"] = callbacks
    result = await graph.ainvoke(
        Command(
            resume={
                "approved": approved,
                "payment_method_id": payment_method_id,
            }
        ),
        config=config,
    )
    result["thread_id"] = thread_id
    await _finalize_turn(thread_id, result)
    return result


_background_tasks: set[asyncio.Task] = set()


async def _drain_graph(
    graph, config: dict, graph_input, thread_id: str, queue: asyncio.Queue
) -> None:
    """Run one graph turn to completion/pause, forwarding every chunk to `queue`.

    Runs as a detached background task (see `_stream_turn`) so a client
    disconnecting from the SSE response can never cut the graph run short or
    skip `_finalize_turn` — the turn is recorded exactly once, regardless of
    whether anyone was still listening when it finished.
    """

    try:
        interrupt_chunk = None
        async for chunk in graph.astream(graph_input, config=config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                interrupt_chunk = chunk["__interrupt__"]
            await queue.put(("chunk", chunk))

        snapshot = await graph.aget_state(config)
        result = dict(snapshot.values)
        result["thread_id"] = thread_id
        if interrupt_chunk is not None:
            result["__interrupt__"] = interrupt_chunk
        await _finalize_turn(thread_id, result)
        await queue.put(("done", result))
    except Exception as error:
        logger.exception("Streamed turn failed for thread %s", thread_id)
        await queue.put(("error", error))


async def _stream_turn(graph_input, thread_id: str) -> AsyncIterator[dict]:
    """Drive one graph turn as a detached task, yielding its chunks live.

    The task keeps running even if the caller stops iterating (e.g. an HTTP
    client disconnects), so `_finalize_turn` always runs exactly once.
    """

    graph = await get_graph()
    config: dict = {"configurable": {"thread_id": thread_id}}
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_drain_graph(graph, config, graph_input, thread_id, queue))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    while True:
        kind, payload = await queue.get()
        yield {"kind": kind, "payload": payload}
        if kind in ("done", "error"):
            return


async def stream_send_message(user_input: str, thread_id: str | None = None) -> AsyncIterator[dict]:
    """Stream one turn's per-node progress, then its final result.

    Mirrors `send_message`'s setup exactly; only the execution/notification
    mechanism differs (astream + queue instead of one blocking ainvoke).
    """

    thread_id = thread_id or str(uuid4())
    await create_thread(thread_id)
    await _save_message(thread_id, "user", user_input)
    project = await get_project(thread_id)
    graph_input = new_state(user_input, thread_id=thread_id, project=project)
    async for item in _stream_turn(graph_input, thread_id):
        yield item


async def stream_resume_thread(
    thread_id: str,
    approved: bool,
    payment_method_id: str | None = None,
) -> AsyncIterator[dict]:
    """Stream a paused thread's resumption the same way `stream_send_message` does."""

    command = Command(
        resume={"approved": approved, "payment_method_id": payment_method_id}
    )
    async for item in _stream_turn(command, thread_id):
        yield item


async def get_graph():
    """Compile and reuse the checkpointed conversation graph."""

    await initialize()
    return _graph


async def create_thread(thread_id: str | None = None) -> str:
    """Register a conversation thread and return its identifier."""

    await initialize()
    thread_id = thread_id or str(uuid4())
    await _connection.execute(
        "INSERT OR IGNORE INTO chat_threads (thread_id) VALUES (?)",
        (thread_id,),
    )
    await _connection.commit()
    return thread_id


async def get_history(thread_id: str) -> list[dict[str, str]] | None:
    """Return ordered public messages, or None when the thread does not exist."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT 1 FROM chat_threads WHERE thread_id = ?",
        (thread_id,),
    )
    exists = await cursor.fetchone()
    await cursor.close()
    if exists is None:
        return None

    cursor = await _connection.execute(
        """
        SELECT role, content, created_at
        FROM chat_messages
        WHERE thread_id = ?
        ORDER BY id ASC
        """,
        (thread_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {"role": role, "content": content, "created_at": created_at}
        for role, content, created_at in rows
    ]


async def list_threads(limit: int = 50) -> list[dict[str, str]]:
    """List conversations, preferring the generated title over the raw first message."""

    await initialize()
    cursor = await _connection.execute(
        """
        SELECT
            t.thread_id,
            COALESCE(
                t.title,
                (
                    SELECT SUBSTR(first_message.content, 1, 60)
                    FROM chat_messages AS first_message
                    WHERE first_message.thread_id = t.thread_id
                      AND first_message.role = 'user'
                    ORDER BY first_message.id ASC
                    LIMIT 1
                ),
                'New conversation'
            ) AS title,
            t.created_at,
            COALESCE(MAX(m.created_at), t.created_at) AS updated_at
        FROM chat_threads AS t
        LEFT JOIN chat_messages AS m ON m.thread_id = t.thread_id
        GROUP BY t.thread_id, t.created_at
        ORDER BY updated_at DESC, t.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "thread_id": thread_id,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        for thread_id, title, created_at, updated_at in rows
    ]


async def delete_thread(thread_id: str) -> bool:
    """Delete a conversation, its artifacts, and all graph checkpoints."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT 1 FROM chat_threads WHERE thread_id = ?",
        (thread_id,),
    )
    exists = await cursor.fetchone()
    await cursor.close()
    if exists is None:
        return False

    await _checkpointer.adelete_thread(thread_id)
    await _connection.execute("DELETE FROM chat_artifacts WHERE thread_id = ?", (thread_id,))
    await _connection.execute("DELETE FROM chat_wiring_plans WHERE thread_id = ?", (thread_id,))
    await _connection.execute("DELETE FROM chat_purchase_refs WHERE thread_id = ?", (thread_id,))
    await _connection.execute("DELETE FROM chat_projects WHERE thread_id = ?", (thread_id,))
    await _connection.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
    await _connection.execute("DELETE FROM chat_threads WHERE thread_id = ?", (thread_id,))
    await _connection.commit()
    return True


async def register_artifacts(thread_id: str, paths: list[str]) -> list[str]:
    """Store validated image paths under opaque public identifiers."""

    await initialize()
    artifact_ids = []
    for raw_path in paths:
        path = valid_image(raw_path)
        if path is None:
            continue
        artifact_id = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        await _connection.execute(
            """
            INSERT OR IGNORE INTO chat_artifacts (thread_id, artifact_id, path)
            VALUES (?, ?, ?)
            """,
            (thread_id, artifact_id, str(path)),
        )
        artifact_ids.append(artifact_id)
    await _connection.commit()
    return artifact_ids


async def list_artifacts(thread_id: str) -> list[str]:
    """Return image identifiers associated with a conversation."""

    await initialize()
    cursor = await _connection.execute(
        """
        SELECT artifact_id FROM chat_artifacts
        WHERE thread_id = ? ORDER BY created_at, artifact_id
        """,
        (thread_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [row[0] for row in rows]


async def get_artifact(artifact_id: str):
    """Resolve a registered image ID without accepting filesystem input."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT path FROM chat_artifacts WHERE artifact_id = ? LIMIT 1",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return valid_image(row[0])


async def save_wiring(thread_id: str, plan: dict) -> None:
    """Persist the latest wiring plan produced for a conversation."""

    await initialize()
    await _connection.execute(
        """
        INSERT INTO chat_wiring_plans (thread_id, plan_json)
        VALUES (?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            plan_json = excluded.plan_json,
            created_at = CURRENT_TIMESTAMP
        """,
        (thread_id, json.dumps(plan)),
    )
    await _connection.commit()


async def get_wiring(thread_id: str) -> dict | None:
    """Return the latest wiring plan saved for a conversation, if any."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT plan_json FROM chat_wiring_plans WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return json.loads(row[0])


async def save_project(thread_id: str, project: dict) -> None:
    """Persist the complete structured project state for subsequent turns."""

    await initialize()
    await _connection.execute(
        """
        INSERT INTO chat_projects (thread_id, project_json)
        VALUES (?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            project_json = excluded.project_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (thread_id, json.dumps(project)),
    )
    await _connection.commit()


async def get_project(thread_id: str) -> dict | None:
    """Load the complete project, with legacy wiring/purchase fallback."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT project_json FROM chat_projects WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        return json.loads(row[0])

    wiring = await get_wiring(thread_id)
    purchase = await get_purchase(thread_id)
    if wiring is None and purchase is None:
        return None
    return {
        "board": wiring.get("board") if wiring else None,
        "components": wiring.get("components", []) if wiring else [],
        "wiring": wiring,
        "code_artifact": None,
        "model_artifact": None,
        "purchase": purchase,
        "product_cards": [],
    }


async def save_purchase(thread_id: str, reference: dict) -> None:
    """Persist a thin pointer (proposal/order id + status) to a submitted order.

    Financial detail (price, total, currency) is not stored here; System B
    remains the sole audit trail for that, per the proposal's requirement
    that deleting a chat must not delete or cancel an order.
    """

    await initialize()
    await _connection.execute(
        """
        INSERT INTO chat_purchase_refs (thread_id, proposal_id, order_id, status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            proposal_id = excluded.proposal_id,
            order_id = excluded.order_id,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            thread_id,
            reference.get("proposal_id"),
            reference.get("order_id"),
            reference.get("status"),
        ),
    )
    await _connection.commit()


async def get_purchase(thread_id: str) -> dict | None:
    """Return the latest purchase reference saved for a conversation, if any."""

    await initialize()
    cursor = await _connection.execute(
        "SELECT proposal_id, order_id, status FROM chat_purchase_refs WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return {"proposal_id": row[0], "order_id": row[1], "status": row[2]}


async def _save_message(thread_id: str, role: str, content: str) -> None:
    """Persist a message intended for display in public chat history."""

    await _connection.execute(
        """
        INSERT INTO chat_messages (thread_id, role, content)
        VALUES (?, ?, ?)
        """,
        (thread_id, role, content),
    )
    await _connection.commit()


async def _maybe_generate_title(thread_id: str, answer: str) -> None:
    """Set a short LLM-generated title the first time a thread gets a reply.

    No-ops once a title is already stored, so this only ever costs one model
    call per thread. Falls back to the truncated first message on any
    failure (missing key, provider outage after the OpenRouter fallback), so a
    broken title generation never blocks the chat response itself.
    """

    cursor = await _connection.execute(
        "SELECT title FROM chat_threads WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row[0] is not None:
        return

    cursor = await _connection.execute(
        """
        SELECT content FROM chat_messages
        WHERE thread_id = ? AND role = 'user'
        ORDER BY id ASC
        LIMIT 1
        """,
        (thread_id,),
    )
    first_message = await cursor.fetchone()
    await cursor.close()
    user_input = first_message[0] if first_message else ""

    title = None
    try:
        from app.models import title_model

        response = await title_model().ainvoke(
            [
                HumanMessage(
                    content=(
                        "Write a short chat title (max 6 words, no quotes, no "
                        "trailing punctuation) summarizing this exchange.\n\n"
                        f"User: {user_input}\nAssistant: {answer}"
                    )
                )
            ]
        )
        title = to_text(response.content).strip().strip('"').strip() or None
    except Exception:
        logger.exception("Title generation failed for thread %s", thread_id)
        title = None

    if not title:
        title = user_input.strip()[:60] or "New conversation"

    await _connection.execute(
        "UPDATE chat_threads SET title = ? WHERE thread_id = ?",
        (title[:80], thread_id),
    )
    await _connection.commit()
