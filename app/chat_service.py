"""Conversation and thread lifecycle for the multi-agent graph."""

import asyncio
import hashlib
from uuid import uuid4

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.config import settings
from app.graph import build_graph, new_state

_connection: aiosqlite.Connection | None = None
_checkpointer: AsyncSqliteSaver | None = None
_graph = None
_initialization_lock = asyncio.Lock()


async def initialize_chat_service() -> None:
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
            """
        )
        await _connection.commit()
        _graph = build_graph(checkpointer=_checkpointer)


async def close_chat_service() -> None:
    """Close SQLite cleanly when the application shuts down."""

    global _checkpointer, _connection, _graph

    _graph = None
    _checkpointer = None
    if _connection is not None:
        await _connection.close()
        _connection = None


async def send_message(user_input: str, thread_id: str | None = None) -> dict:
    """Send a message on a new or existing conversation thread."""

    thread_id = thread_id or str(uuid4())
    await create_thread(thread_id)
    await _save_message(thread_id, "user", user_input)
    graph = await get_graph()
    result = await graph.ainvoke(
        new_state(user_input, thread_id=thread_id),
        config={"configurable": {"thread_id": thread_id}},
    )
    result["thread_id"] = thread_id
    if result.get("final_answer") and not result.get("__interrupt__"):
        await _save_message(thread_id, "assistant", result["final_answer"])
        await register_artifacts(thread_id, result.get("image_paths", []))
    return result


async def resume_thread(thread_id: str, approved: bool) -> dict:
    """Resume a paused thread with its human approval decision."""

    graph = await get_graph()
    result = await graph.ainvoke(
        Command(resume={"approved": approved}),
        config={"configurable": {"thread_id": thread_id}},
    )
    result["thread_id"] = thread_id
    if result.get("final_answer") and not result.get("__interrupt__"):
        await _save_message(thread_id, "assistant", result["final_answer"])
        await register_artifacts(thread_id, result.get("image_paths", []))
    return result


async def get_graph():
    """Compile and reuse the checkpointed conversation graph."""

    await initialize_chat_service()
    return _graph


async def create_thread(thread_id: str | None = None) -> str:
    """Register a conversation thread and return its identifier."""

    await initialize_chat_service()
    thread_id = thread_id or str(uuid4())
    await _connection.execute(
        "INSERT OR IGNORE INTO chat_threads (thread_id) VALUES (?)",
        (thread_id,),
    )
    await _connection.commit()
    return thread_id


async def get_thread_history(thread_id: str) -> list[dict[str, str]] | None:
    """Return ordered public messages, or None when the thread does not exist."""

    await initialize_chat_service()
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
    """List conversations, using the first user message as a short title."""

    await initialize_chat_service()
    cursor = await _connection.execute(
        """
        SELECT
            t.thread_id,
            COALESCE(
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

    await initialize_chat_service()
    cursor = await _connection.execute(
        "SELECT 1 FROM chat_threads WHERE thread_id = ?",
        (thread_id,),
    )
    exists = await cursor.fetchone()
    await cursor.close()
    if exists is None:
        return False

    await _checkpointer.adelete_thread(thread_id)
    await _connection.execute(
        "DELETE FROM chat_artifacts WHERE thread_id = ?", (thread_id,)
    )
    await _connection.execute(
        "DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,)
    )
    await _connection.execute(
        "DELETE FROM chat_threads WHERE thread_id = ?", (thread_id,)
    )
    await _connection.commit()
    return True


async def register_artifacts(thread_id: str, paths: list[str]) -> list[str]:
    """Store validated image paths under opaque public identifiers."""

    await initialize_chat_service()
    artifact_ids = []
    for raw_path in paths:
        path = _validated_image_path(raw_path)
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


async def get_thread_artifact_ids(thread_id: str) -> list[str]:
    """Return image identifiers associated with a conversation."""

    await initialize_chat_service()
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


async def get_artifact_path(artifact_id: str):
    """Resolve a registered image ID without accepting filesystem input."""

    await initialize_chat_service()
    cursor = await _connection.execute(
        "SELECT path FROM chat_artifacts WHERE artifact_id = ? LIMIT 1",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return _validated_image_path(row[0])


def _validated_image_path(raw_path: str):
    """Allow only existing images under configured generated or RAG roots."""

    from pathlib import Path

    path = Path(raw_path).resolve()
    allowed_roots = [
        settings.generated_directory.resolve(),
        settings.rag_project_path.resolve(),
    ]
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    if not path.is_file() or not any(path.is_relative_to(root) for root in allowed_roots):
        return None
    return path


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
