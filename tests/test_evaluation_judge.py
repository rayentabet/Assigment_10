"""Task-completion judge grading, without any real model call."""

import pytest

from evaluation.judge import TaskCompletionVerdict, judge_task_completion


class FakeJudge:
    def __init__(self, verdict: TaskCompletionVerdict) -> None:
        self._verdict = verdict

    async def ainvoke(self, prompt):
        return self._verdict


class FakeModel:
    def __init__(self, verdict: TaskCompletionVerdict) -> None:
        self._verdict = verdict

    def with_structured_output(self, *args, **kwargs):
        return FakeJudge(self._verdict)


@pytest.mark.asyncio
async def test_skips_cases_without_a_task_completion_goal():
    case = {"id": "no_goal", "query": "Hello", "expected": {}}

    result = await judge_task_completion(case, {"answer": "Hi there!"})

    assert result == {"task_completion_correct": None, "task_completion_reasoning": None}


@pytest.mark.asyncio
async def test_returns_the_judge_verdict_and_reasoning(monkeypatch):
    verdict = TaskCompletionVerdict(passed=True, reasoning="Answer states 32/2/1 KB correctly.")
    monkeypatch.setattr("app.models.judge_model", lambda: FakeModel(verdict))
    case = {
        "id": "rag_uno_memory",
        "query": "How much Flash, SRAM, and EEPROM does the Arduino Uno R3 have?",
        "expected": {"task_completion": {"goal": "States 32KB/2KB/1KB correctly."}},
    }

    result = await judge_task_completion(case, {"answer": "32KB Flash, 2KB SRAM, 1KB EEPROM."})

    assert result["task_completion_correct"] is True
    assert result["task_completion_reasoning"] == verdict.reasoning


@pytest.mark.asyncio
async def test_reports_a_failing_verdict(monkeypatch):
    verdict = TaskCompletionVerdict(passed=False, reasoning="Refused to give the total.")
    monkeypatch.setattr("app.models.judge_model", lambda: FakeModel(verdict))
    case = {
        "id": "refuses_total",
        "query": "What's the total cost?",
        "expected": {"task_completion": {"goal": "States the numeric total."}},
    }

    result = await judge_task_completion(case, {"answer": "I can't calculate that."})

    assert result["task_completion_correct"] is False
    assert "Refused" in result["task_completion_reasoning"]


class RaisingJudge:
    async def ainvoke(self, prompt):
        raise ValueError("output_parse_failed: model emitted chain-of-thought, not JSON")


class RaisingModel:
    def with_structured_output(self, *args, **kwargs):
        return RaisingJudge()


@pytest.mark.asyncio
async def test_a_judge_call_failure_does_not_propagate(monkeypatch):
    """One case's judge error must degrade gracefully, not crash the whole eval run —
    this is exactly what happened live: a Groq 400 on a reasoning model's unparseable
    output took down the entire harness mid-run before this guard was added."""

    monkeypatch.setattr("app.models.judge_model", lambda: RaisingModel())
    case = {
        "id": "flaky_judge",
        "query": "Wire an HC-SR04 sensor to a Raspberry Pi 5.",
        "expected": {"task_completion": {"goal": "Provides a valid wiring plan."}},
    }

    result = await judge_task_completion(case, {"answer": "Here is the wiring plan..."})

    assert result["task_completion_correct"] is None
    assert "judge error" in result["task_completion_reasoning"]
