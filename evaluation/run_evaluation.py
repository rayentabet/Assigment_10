"""Run the v2 System A routing, tool, approval, and guardrail evaluation."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from app import chat_service
from app.chat_service import resume_thread, send_message
from app.config import settings
from app.guardrails import BLOCKED_MESSAGE
from evaluation.comparators import aggregate_summary, call_entries, compare_case
from evaluation.cost_tracking import UsageCollector
from evaluation.judge import judge_task_completion

HERE = Path(__file__).parent
DATASET = HERE / "golden_dataset" / "v2" / "cases.jsonl"
RUNS_DIRECTORY = HERE / "runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default="system_a_v2")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run one case ID")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument(
        "--exclude-requires",
        action="store_true",
        help="Skip cases that declare an external service/credential requirement",
    )
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args()


def load_cases(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def select_cases(cases: list[dict], args: argparse.Namespace) -> list[dict]:
    selected = cases
    if args.case_ids:
        requested = set(args.case_ids)
        selected = [case for case in selected if case["id"] in requested]
        missing = requested - {case["id"] for case in selected}
        if missing:
            raise ValueError(f"Unknown case ID(s): {sorted(missing)}")
    if args.categories:
        selected = [case for case in selected if case["category"] in set(args.categories)]
    if args.tags:
        selected = [case for case in selected if set(args.tags) <= set(case.get("tags", []))]
    if args.exclude_requires:
        selected = [case for case in selected if not case.get("requires")]
    if not selected:
        raise ValueError("No cases matched the selected filters")
    return selected


def create_run_directory(name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "evaluation"
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    directory = RUNS_DIRECTORY / f"{timestamp}_{safe_name}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def interrupt_payload(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return None
    payload = getattr(interrupts[0], "value", interrupts[0])
    return payload if isinstance(payload, dict) else {"value": payload}


def guardrail_outcome(case: dict, result: dict, answer: str) -> str:
    if answer == BLOCKED_MESSAGE or result.get("input_blocked"):
        return "blocked"
    sensitive = case.get("sensitive_values", [])
    safe_input = result.get("original_query", case.get("query", ""))
    if sensitive and all(value not in safe_input and value not in answer for value in sensitive):
        return "masked"
    return "passed"


async def _invoke_case(case: dict) -> dict:
    approvals: list[dict] = []
    steps: list[dict] = []
    result: dict = {}
    thread_id: str | None = None
    turns = case.get("turns") or [{"query": case["query"]}]
    collector = UsageCollector()

    for turn in turns:
        if "query" in turn:
            result = await send_message(turn["query"], thread_id=thread_id, callbacks=[collector])
            thread_id = result["thread_id"]
            operation = "query"
        elif "resume" in turn:
            decision = bool(turn["resume"]["approved"])
            if approvals and approvals[-1]["decision"] == "pending":
                approvals[-1]["decision"] = "approved" if decision else "rejected"
            result = await resume_thread(
                thread_id or "",
                decision,
                payment_method_id=turn["resume"].get("payment_method_id"),
                callbacks=[collector],
            )
            operation = "resume"
        else:
            raise ValueError(f"Unsupported turn in {case['id']}: {turn}")

        payload = interrupt_payload(result)
        if payload:
            approvals.append(
                {
                    "action": payload.get("action"),
                    "decision": "pending",
                    "payload": payload,
                }
            )
        steps.append(
            {
                "operation": operation,
                "route_history": result.get("route_history", []),
                "interrupt": payload,
            }
        )

    answer = result.get("final_answer") or ""
    return {
        "result": result,
        "answer": answer,
        "tool_trace": result.get("tool_trace", []),
        "approvals": approvals,
        "steps": steps,
        "guardrail": guardrail_outcome(case, result, answer),
        "usage": collector.usage_summary(),
        "error": None,
    }


async def execute_case(case: dict) -> dict:
    simulation = case.get("simulate", {}).get("type")
    if simulation != "system_b_unreachable":
        return await _invoke_case(case)

    from app.integrations import component_client

    original = (
        settings.component_manager_a2a_url,
        settings.a2a_timeout_seconds,
        settings.a2a_max_retries,
    )
    try:
        settings.component_manager_a2a_url = "http://127.0.0.1:1"
        settings.a2a_timeout_seconds = 0.25
        settings.a2a_max_retries = 0
        component_client._client = None
        return await _invoke_case(case)
    finally:
        (
            settings.component_manager_a2a_url,
            settings.a2a_timeout_seconds,
            settings.a2a_max_retries,
        ) = original
        component_client._client = None


def public_result(case: dict, execution: dict, comparison: dict, duration_ms: float) -> dict:
    state = execution.get("result", {})
    iteration_count = state.get("iteration_count", 0)
    min_steps = case["expected"].get("min_steps")
    usage = execution.get("usage", {})
    return {
        "id": case["id"],
        "category": case["category"],
        "tags": case.get("tags", []),
        "requires": case.get("requires", []),
        "query": case.get("query") or next(
            (turn["query"] for turn in case.get("turns", []) if "query" in turn), ""
        ),
        "expected": case["expected"],
        "expected_routes": case["expected"].get("routes", []),
        "actual_routes": state.get("route_history", []),
        "expected_guardrail": case["expected"].get("guardrail"),
        "actual_guardrail": execution.get("guardrail"),
        "duration_ms": round(duration_ms, 3),
        "iteration_count": iteration_count,
        "min_steps": min_steps,
        "step_efficiency_ratio": (
            round(iteration_count / min_steps, 3) if min_steps else None
        ),
        "answer": execution.get("answer", ""),
        "approvals": execution.get("approvals", []),
        "steps": execution.get("steps", []),
        "tool_calls": call_entries(execution.get("tool_trace", [])),
        "tool_trace": execution.get("tool_trace", []),
        "project": state.get("project", {}),
        "total_input_tokens": usage.get("total_input_tokens", 0),
        "total_output_tokens": usage.get("total_output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "cost_usd": usage.get("cost_usd"),
        "unpriced_models": usage.get("unpriced_models", []),
        "tokens_by_node": usage.get("tokens_by_node", {}),
        "error": execution.get("error"),
        **comparison,
    }


def error_execution(error: Exception) -> dict:
    return {
        "result": {},
        "answer": "",
        "tool_trace": [],
        "approvals": [],
        "steps": [],
        "guardrail": "error",
        "usage": UsageCollector().usage_summary(),
        "error": f"{type(error).__name__}: {error}",
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = [
        "id",
        "category",
        "case_pass",
        "route_correct",
        "tool_selection_correct",
        "tool_arguments_correct",
        "tool_order_correct",
        "approval_correct",
        "guardrail_correct",
        "project_correct",
        "cross_check_correct",
        "recovery_correct",
        "task_completion_correct",
        "expected_routes",
        "actual_routes",
        "duration_ms",
        "iteration_count",
        "min_steps",
        "step_efficiency_ratio",
        "total_tokens",
        "cost_usd",
        "failures",
    ]
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row[key], ensure_ascii=False)
                    if isinstance(row.get(key), (list, dict))
                    else row.get(key)
                    for key in columns
                }
            )


async def main() -> None:
    args = parse_args()
    cases = select_cases(load_cases(), args)
    run_directory = create_run_directory(args.run_name)
    results_path = run_directory / "case_results.jsonl"
    csv_path = run_directory / "results.csv"
    metadata_path = run_directory / "metadata.json"
    summary_path = run_directory / "summary.json"
    started = datetime.now(UTC)
    results = []

    metadata = {
        "schema_version": 2,
        "dataset": str(DATASET),
        "name": args.run_name,
        "status": "running",
        "started_at": started.isoformat(),
        "completed_at": None,
        "selected_cases": [case["id"] for case in cases],
        "models": {
            "supervisor": settings.supervisor_model,
            "guardrails": settings.guardrail_model,
            "rag": settings.rag_model,
            "coding": settings.code_model,
            "wiring": settings.wiring_model,
            "visualization": settings.visualization_model,
            "judge": settings.judge_model,
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    try:
        for case in cases:
            started_case = time.perf_counter()
            try:
                execution = await execute_case(case)
            except Exception as error:  # noqa: BLE001 - one failed case must not end the run
                execution = error_execution(error)
            comparison = compare_case(case, execution)
            comparison = {**comparison, **await judge_task_completion(case, execution)}
            result = public_result(
                case, execution, comparison, (time.perf_counter() - started_case) * 1000
            )
            results.append(result)
            write_jsonl(results_path, results)
            write_csv(csv_path, results)
            summary_path.write_text(
                json.dumps(aggregate_summary(results), indent=2), encoding="utf-8"
            )
            print(
                f"{'PASS' if result['case_pass'] else 'FAIL'}: {case['id']} "
                f"({' -> '.join(result['actual_routes']) or 'FINISH'})",
                flush=True,
            )
            if args.fail_fast and not result["case_pass"]:
                break
    finally:
        metadata["status"] = "completed" if len(results) == len(cases) else "interrupted"
        metadata["completed_at"] = datetime.now(UTC).isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        await chat_service.shutdown()

    summary = aggregate_summary(results)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    passed = summary["metrics"]["case_pass"]["passed"]
    print(f"\nCases passed: {passed}/{len(results)}")
    if summary["unpriced_models"]:
        print(
            "Cost tracking incomplete: no pricing for "
            f"{', '.join(summary['unpriced_models'])} in evaluation/cost_tracking.py"
            " (cost_usd is None for cases using them)"
        )
    print(f"Saved run: {run_directory}")


if __name__ == "__main__":
    asyncio.run(main())
