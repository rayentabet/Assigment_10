from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def disable_artifact_database(monkeypatch):
    async def fake_get_thread_artifact_ids(thread_id: str):
        return []

    monkeypatch.setattr(
        main, "get_thread_artifact_ids", fake_get_thread_artifact_ids
    )


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_thread(monkeypatch) -> None:
    async def fake_register_thread(thread_id: str):
        return thread_id

    monkeypatch.setattr(main, "register_thread", fake_register_thread)

    response = client.post("/threads")

    assert response.status_code == 201
    assert response.json()["thread_id"]


def test_post_message_returns_answer(monkeypatch) -> None:
    async def fake_send_message(message: str, thread_id: str):
        return {
            "thread_id": thread_id,
            "final_answer": f"Answer to: {message}",
        }

    monkeypatch.setattr(main, "send_message", fake_send_message)

    response = client.post(
        "/threads/thread-123/messages",
        json={"message": "Hello"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-123",
        "status": "completed",
        "answer": "Answer to: Hello",
        "approval": None,
        "image_urls": [],
    }


def test_post_message_returns_approval_request(monkeypatch) -> None:
    async def fake_send_message(message: str, thread_id: str):
        request = {
            "question": "Approve running coding_agent?",
            "action": "coding_agent",
            "task": "Write Arduino code",
            "reason": "This specialist may write generated files.",
        }
        return {
            "thread_id": thread_id,
            "__interrupt__": [SimpleNamespace(value=request)],
        }

    monkeypatch.setattr(main, "send_message", fake_send_message)

    response = client.post(
        "/threads/thread-123/messages",
        json={"message": "Write Arduino code"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approval_required"
    assert response.json()["approval"]["action"] == "coding_agent"


def test_blank_message_is_rejected() -> None:
    response = client.post(
        "/threads/thread-123/messages",
        json={"message": "   "},
    )

    assert response.status_code == 422


def test_get_thread_messages(monkeypatch) -> None:
    async def fake_get_thread_history(thread_id: str):
        return [
            {
                "role": "user",
                "content": "Hello",
                "created_at": "2026-08-06 12:00:00",
            },
            {
                "role": "assistant",
                "content": "Hi!",
                "created_at": "2026-08-06 12:00:01",
            },
        ]

    monkeypatch.setattr(main, "get_thread_history", fake_get_thread_history)

    response = client.get("/threads/thread-123/messages")

    assert response.status_code == 200
    assert [message["role"] for message in response.json()["messages"]] == [
        "user",
        "assistant",
    ]


def test_get_unknown_thread_returns_404(monkeypatch) -> None:
    async def fake_get_thread_history(thread_id: str):
        return None

    monkeypatch.setattr(main, "get_thread_history", fake_get_thread_history)

    response = client.get("/threads/missing/messages")

    assert response.status_code == 404


def test_list_threads(monkeypatch) -> None:
    async def fake_list_threads():
        return [
            {
                "thread_id": "thread-123",
                "title": "Hello robot",
                "created_at": "2026-08-06 12:00:00",
                "updated_at": "2026-08-06 12:00:01",
            }
        ]

    monkeypatch.setattr(main, "list_threads", fake_list_threads)

    response = client.get("/threads")

    assert response.status_code == 200
    assert response.json()["threads"][0]["title"] == "Hello robot"


def test_delete_thread(monkeypatch) -> None:
    async def fake_delete_thread(thread_id: str):
        return True

    monkeypatch.setattr(main, "delete_thread", fake_delete_thread)

    response = client.delete("/threads/thread-123")

    assert response.status_code == 204
    assert response.content == b""


def test_delete_unknown_thread_returns_404(monkeypatch) -> None:
    async def fake_delete_thread(thread_id: str):
        return False

    monkeypatch.setattr(main, "delete_thread", fake_delete_thread)

    response = client.delete("/threads/missing")

    assert response.status_code == 404
