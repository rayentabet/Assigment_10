"""Step-efficiency and cost/token fields added to the evaluation harness."""

import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from evaluation.comparators import aggregate_summary
from evaluation.cost_tracking import MODEL_PRICING, UsageCollector
from evaluation.run_evaluation import public_result


def _case(min_steps=None):
    expected = {"routes": ["wiring_agent"]}
    if min_steps is not None:
        expected["min_steps"] = min_steps
    return {"id": "c1", "category": "routing", "expected": expected, "query": "q"}


def _execution(iteration_count=0, usage=None):
    return {
        "result": {"route_history": ["wiring_agent"], "iteration_count": iteration_count},
        "answer": "done",
        "tool_trace": [],
        "approvals": [],
        "steps": [],
        "guardrail": "passed",
        "usage": usage or {},
        "error": None,
    }


def test_step_efficiency_ratio_is_none_without_a_min_steps_reference():
    result = public_result(_case(), _execution(iteration_count=3), {}, 10.0)

    assert result["min_steps"] is None
    assert result["step_efficiency_ratio"] is None


def test_step_efficiency_ratio_divides_actual_by_expected():
    result = public_result(_case(min_steps=2), _execution(iteration_count=3), {}, 10.0)

    assert result["step_efficiency_ratio"] == 1.5


def test_cost_and_token_fields_default_safely_without_usage_data():
    result = public_result(_case(), _execution(), {}, 10.0)

    assert result["total_tokens"] == 0
    assert result["cost_usd"] is None
    assert result["unpriced_models"] == []


def test_usage_collector_reports_none_cost_for_unpriced_models():
    collector = UsageCollector()
    collector.calls = [
        {
            "model": "some-unpriced-model",
            "node": "wiring_agent",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
    ]

    summary = collector.usage_summary()

    assert summary["total_tokens"] == 150
    assert summary["cost_usd"] is None
    assert summary["unpriced_models"] == ["some-unpriced-model"]
    assert summary["tokens_by_node"]["wiring_agent"] == {"input_tokens": 100, "output_tokens": 50}


def test_usage_collector_prices_calls_present_in_model_pricing(monkeypatch):
    monkeypatch.setitem(MODEL_PRICING, "priced-model", (1.0, 2.0))
    collector = UsageCollector()
    collector.calls = [
        {
            "model": "priced-model",
            "node": None,
            "input_tokens": 1_000_000,
            "output_tokens": 500_000,
            "total_tokens": 1_500_000,
        }
    ]

    summary = collector.usage_summary()

    assert summary["cost_usd"] == 2.0
    assert summary["unpriced_models"] == []


@pytest.mark.asyncio
async def test_usage_collector_attributes_tokens_to_the_node_from_llm_start():
    """`on_llm_end` doesn't carry `metadata` in LangChain's callback API — only
    `on_chat_model_start` does. The node must be captured there and looked up
    by `run_id` in `on_llm_end`, not read from `on_llm_end`'s kwargs directly."""

    collector = UsageCollector()
    run_id = uuid.uuid4()
    message = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    response = LLMResult(
        generations=[[ChatGeneration(message=message)]], llm_output={"model_name": "m"}
    )

    await collector.on_chat_model_start(
        {}, [[]], run_id=run_id, metadata={"langgraph_node": "wiring_agent"}
    )
    await collector.on_llm_end(response, run_id=run_id)

    summary = collector.usage_summary()
    assert summary["tokens_by_node"] == {"wiring_agent": {"input_tokens": 10, "output_tokens": 5}}


def test_aggregate_summary_averages_step_efficiency_and_cost():
    results = [
        {
            **public_result(_case(min_steps=2), _execution(iteration_count=2), {}, 1.0),
            "cost_usd": 0.01,
            "total_tokens": 100,
        },
        {
            **public_result(_case(min_steps=2), _execution(iteration_count=4), {}, 1.0),
            "cost_usd": 0.03,
            "total_tokens": 300,
        },
    ]

    summary = aggregate_summary(results)

    assert summary["mean_step_efficiency_ratio"] == 1.5
    assert summary["mean_cost_usd"] == 0.02
    assert summary["total_cost_usd"] == 0.04
    assert summary["mean_total_tokens"] == 200
