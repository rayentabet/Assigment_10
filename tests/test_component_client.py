import pytest
from a2a.helpers.proto_helpers import new_data_message, new_text_message
from a2a.types import a2a_pb2

from app.integrations import component_client


class _FakeClient:
    """A minimal Client double returning canned responses, no network calls."""

    def __init__(self, responses, get_task_result=None, error: Exception | None = None):
        self._responses = responses
        self._get_task_result = get_task_result
        self._error = error
        self.sent_requests = []
        self.get_task_calls = 0

    async def send_message(self, request):
        self.sent_requests.append(request)
        if self._error is not None:
            raise self._error
        for response in self._responses:
            yield response

    async def get_task(self, request):
        self.get_task_calls += 1
        return self._get_task_result


def _call_entry(tool: str, call_id: str, args: dict) -> a2a_pb2.Message:
    return new_data_message({"name": tool, "id": call_id, "args": args})


def _result_entry(tool: str, call_id: str, response: dict) -> a2a_pb2.Message:
    return new_data_message({"name": tool, "id": call_id, "response": response})


def _completed_task(history: list, answer: str) -> a2a_pb2.StreamResponse:
    artifact = a2a_pb2.Artifact(artifact_id="a1", parts=new_text_message(answer).parts)
    status = a2a_pb2.TaskStatus(state=a2a_pb2.TaskState.TASK_STATE_COMPLETED)
    task = a2a_pb2.Task(id="task-1", status=status, artifacts=[artifact], history=history)
    return a2a_pb2.StreamResponse(task=task)


def _failed_task(error_text: str) -> a2a_pb2.StreamResponse:
    status = a2a_pb2.TaskStatus(
        state=a2a_pb2.TaskState.TASK_STATE_FAILED,
        message=new_text_message(error_text),
    )
    return a2a_pb2.StreamResponse(task=a2a_pb2.Task(id="task-1", status=status))


@pytest.fixture(autouse=True)
def _reset_client():
    component_client._client = None
    yield
    component_client._client = None


@pytest.mark.asyncio
async def test_contact_manager_parses_calls_and_results(monkeypatch) -> None:
    history = [
        new_text_message("Buy 2 hc-sr04 sensors"),
        _call_entry("check_component_availability", "c1", {"component_id": "hc-sr04"}),
        _result_entry(
            "check_component_availability", "c1", {"found": True, "quantity_on_hand": 12}
        ),
        _call_entry("create_digikey_proposal", "c2", {"part_number": "TEST-ND", "quantity": 2}),
        _result_entry(
            "create_digikey_proposal",
            "c2",
            {"success": True, "proposal_id": "PROP-1", "total": 7.42, "approval_token": "tok"},
        ),
    ]
    fake = _FakeClient([_completed_task(history, "Proposal PROP-1 is ready for review.")])
    monkeypatch.setattr(component_client, "_client", fake)

    result = await component_client.contact_manager("Buy 2 hc-sr04 sensors")

    assert result["answer"] == "Proposal PROP-1 is ready for review."
    assert len(result["tool_calls"]) == 2
    assert len(result["tool_results"]) == 2

    proposal = component_client.last_result(result, "create_digikey_proposal")
    assert proposal == {
        "success": True,
        "proposal_id": "PROP-1",
        "total": 7.42,
        "approval_token": "tok",
    }


@pytest.mark.asyncio
async def test_contact_manager_handles_immediate_message(monkeypatch) -> None:
    fake = _FakeClient([a2a_pb2.StreamResponse(message=new_text_message("Sure, ask away."))])
    monkeypatch.setattr(component_client, "_client", fake)

    result = await component_client.contact_manager("hello")

    assert result == {"answer": "Sure, ask away.", "tool_calls": [], "tool_results": []}


@pytest.mark.asyncio
async def test_contact_manager_returns_error_on_failed_task(monkeypatch) -> None:
    fake = _FakeClient([_failed_task("Unknown component: nope")])
    monkeypatch.setattr(component_client, "_client", fake)

    result = await component_client.contact_manager("Buy a nope")

    assert "error" in result
    assert "Unknown component" in result["error"]


@pytest.mark.asyncio
async def test_contact_manager_polls_a_non_terminal_task(monkeypatch) -> None:
    monkeypatch.setattr(component_client, "_POLL_INTERVAL_SECONDS", 0)
    working_status = a2a_pb2.TaskStatus(state=a2a_pb2.TaskState.TASK_STATE_WORKING)
    working_task = a2a_pb2.Task(id="task-1", status=working_status)
    settled = _completed_task([], "Done.").task
    fake = _FakeClient([a2a_pb2.StreamResponse(task=working_task)], get_task_result=settled)
    monkeypatch.setattr(component_client, "_client", fake)

    result = await component_client.contact_manager("Buy 2 hc-sr04 sensors")

    assert result["answer"] == "Done."
    assert fake.get_task_calls >= 1


@pytest.mark.asyncio
async def test_contact_manager_returns_error_after_exhausting_retries(
    monkeypatch,
) -> None:
    monkeypatch.setattr(component_client.settings, "a2a_max_retries", 1)
    fake = _FakeClient([], error=ConnectionError("no route to host"))
    monkeypatch.setattr(component_client, "_client", fake)

    result = await component_client.contact_manager("Buy 2 hc-sr04 sensors")

    assert "error" in result
    assert "Component Manager call failed" in result["error"]


def test_last_result_returns_the_most_recent_match() -> None:
    result = {
        "tool_results": [
            {"tool": "create_digikey_proposal", "id": "c1", "result": {"proposal_id": "DKP-1"}},
            {"tool": "create_digikey_proposal", "id": "c2", "result": {"proposal_id": "DKP-2"}},
        ]
    }

    assert component_client.last_result(result, "create_digikey_proposal") == {
        "proposal_id": "DKP-2"
    }
    assert component_client.last_result(result, "place_digikey_order") is None


def test_last_argument_returns_the_most_recent_match() -> None:
    result = {
        "tool_calls": [
            {"tool": "place_digikey_order", "id": "c1", "arguments": {"proposal_id": "DKP-1"}},
            {"tool": "place_digikey_order", "id": "c2", "arguments": {"proposal_id": "DKP-2"}},
        ]
    }

    argument = component_client.last_argument(result, "place_digikey_order", "proposal_id")
    assert argument == "DKP-2"
    assert component_client.last_argument(result, "get_digikey_order", "order_id") is None
