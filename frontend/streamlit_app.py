"""Streamlit chat client for the FastAPI robotics agent."""

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 300


@st.cache_resource
def api_client() -> httpx.Client:
    """Reuse one HTTP connection pool across Streamlit reruns."""

    return httpx.Client(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)


def api_request(method: str, path: str, **kwargs) -> dict:
    """Call FastAPI and show a readable error when it is unavailable."""

    try:
        response = api_client().request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except ValueError:
            detail = exc.response.text
        raise RuntimeError(str(detail)) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            f"Cannot connect to the API at {API_BASE_URL}. Start FastAPI first."
        ) from exc


def create_thread() -> str:
    """Create a new backend conversation and return its ID."""

    return api_request("POST", "/threads")["thread_id"]


def load_conversation(thread_id: str) -> None:
    """Load public messages and images saved for a conversation."""

    result = api_request("GET", f"/threads/{thread_id}/messages")
    st.session_state.messages = result["messages"]
    st.session_state.image_urls = result.get("image_urls", [])


def list_conversations() -> list[dict]:
    """Load recent conversations for the sidebar selector."""

    return api_request("GET", "/threads")["threads"]


def start_new_chat() -> None:
    """Replace the active conversation with a newly created thread."""

    st.session_state.thread_id = create_thread()
    st.session_state.messages = []
    st.session_state.pending_approval = None
    st.session_state.image_urls = []
    st.session_state.confirm_delete = False


def select_chat_after_delete() -> None:
    """Select another saved chat, creating one only when none remain."""

    conversations = list_conversations()
    if not conversations:
        start_new_chat()
        return

    next_thread_id = conversations[0]["thread_id"]
    st.session_state.thread_id = next_thread_id
    st.session_state.pending_approval = None
    st.session_state.confirm_delete = False
    load_conversation(next_thread_id)


def apply_agent_result(result: dict) -> None:
    """Update UI state from a completed or interrupted agent response."""

    st.session_state.image_urls = list(
        dict.fromkeys(result.get("image_urls", []))
    )
    if result["status"] == "approval_required":
        st.session_state.pending_approval = result["approval"]
        return

    st.session_state.pending_approval = None
    if answer := result.get("answer"):
        st.session_state.messages.append(
            {"role": "assistant", "content": answer}
        )


def initialize_session() -> None:
    """Create the first thread and load history once per browser session."""

    if "thread_id" not in st.session_state:
        start_new_chat()
    if "messages" not in st.session_state:
        load_conversation(st.session_state.thread_id)
    if "pending_approval" not in st.session_state:
        st.session_state.pending_approval = None
    if "image_urls" not in st.session_state:
        st.session_state.image_urls = []
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False


st.set_page_config(page_title="Robotics Agent", page_icon="🤖", layout="centered")
st.title("Robotics Multi-Agent Assistant")
st.caption("FastAPI + LangGraph + SQLite")

try:
    initialize_session()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

with st.sidebar:
    st.subheader("Conversation")
    st.code(st.session_state.thread_id, language=None)
    if st.button("New chat", use_container_width=True):
        try:
            start_new_chat()
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))
    if st.button("Reload history", use_container_width=True):
        try:
            load_conversation(st.session_state.thread_id)
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))
    if st.button("Delete current chat", use_container_width=True):
        st.session_state.confirm_delete = True
    if st.session_state.confirm_delete:
        st.warning("Delete this conversation permanently?")
        confirm_column, cancel_column = st.columns(2)
        if confirm_column.button(
            "Delete", type="primary", use_container_width=True
        ):
            try:
                api_request(
                    "DELETE", f"/threads/{st.session_state.thread_id}"
                )
                select_chat_after_delete()
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))
        if cancel_column.button("Cancel", use_container_width=True):
            st.session_state.confirm_delete = False
            st.rerun()
    st.divider()
    st.subheader("Previous chats")
    try:
        conversations = list_conversations()
        for conversation in conversations:
            selected = conversation["thread_id"] == st.session_state.thread_id
            label = f"{'● ' if selected else ''}{conversation['title']}"
            if st.button(
                label,
                key=f"thread-{conversation['thread_id']}",
                use_container_width=True,
                disabled=selected,
            ):
                st.session_state.thread_id = conversation["thread_id"]
                st.session_state.pending_approval = None
                load_conversation(conversation["thread_id"])
                st.rerun()
    except RuntimeError as exc:
        st.error(str(exc))
    st.caption(f"API: {API_BASE_URL}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

for image_url in st.session_state.image_urls:
    st.image(f"{API_BASE_URL}{image_url}")

if approval := st.session_state.pending_approval:
    with st.chat_message("assistant"):
        st.warning(approval["reason"])
        st.write(f"**Action:** {approval['action']}")
        st.write(f"**Task:** {approval['task']}")
        approve_column, reject_column = st.columns(2)

        if approve_column.button("Approve", type="primary", use_container_width=True):
            try:
                result = api_request(
                    "POST",
                    f"/threads/{st.session_state.thread_id}/resume",
                    json={"approved": True},
                )
                apply_agent_result(result)
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))

        if reject_column.button("Reject", use_container_width=True):
            try:
                result = api_request(
                    "POST",
                    f"/threads/{st.session_state.thread_id}/resume",
                    json={"approved": False},
                )
                apply_agent_result(result)
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))

if prompt := st.chat_input(
    "Ask about robotics, Arduino code, or robot visualization…",
    disabled=st.session_state.pending_approval is not None,
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        with st.spinner("The agent is working…"):
            result = api_request(
                "POST",
                f"/threads/{st.session_state.thread_id}/messages",
                json={"message": prompt},
            )
        apply_agent_result(result)
        st.rerun()
    except RuntimeError as exc:
        st.error(str(exc))
