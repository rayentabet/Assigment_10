"""Run the ten routing and guardrail evaluation cases."""

import argparse
import asyncio
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.chat_service import send_message
from app.guardrails import BLOCKED_MESSAGE, check_output

HERE = Path(__file__).parent
QUERIES_FILE = HERE / "queries.json"
RESULTS_FILE = HERE / "results.csv"
RUNS_DIRECTORY = HERE / "runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default="evaluation", help="Short label for this run")
    return parser.parse_args()


def create_run_directory(name: str) -> Path:
    """Create a safe, timestamped directory for one evaluation run."""

    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "evaluation"
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_directory = RUNS_DIRECTORY / f"{timestamp}_{safe_name}"
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def write_results(results: list[dict[str, Any]], path: Path) -> None:
    """Write accumulated results so partial runs are not lost."""

    if not results:
        return
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)


def write_metadata(path: Path, **values: Any) -> None:
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")


def routes_match(expected: list[str], actual: list[str]) -> bool:
    """Require exactly the expected route sequence."""

    return expected == actual


def failure_reason(
    route_ok: bool, guardrail_ok: bool, answer: str, expected: list[str], actual: list[str]
) -> str:
    problems = []
    if not route_ok:
        problems.append(f"expected routes {expected}, got {actual}")
    if not guardrail_ok:
        problems.append("guardrail outcome did not match")
    if not answer.strip():
        problems.append("empty answer")
    return "; ".join(problems)


async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one full workflow or one supplied output."""

    expected_routes = case["expected_routes"]
    expected_guardrail = case["expected_guardrail"]

    if case.get("mode") == "output_only":
        candidate = case["candidate_output"]
        checked = await check_output(case["query"], candidate, evidence=[])
        answer = checked or BLOCKED_MESSAGE
        raw_answer = candidate
        actual_routes = []
        iteration_count = 0
        actual_guardrail = (
            "blocked" if checked is None else "masked" if checked != candidate else "passed"
        )
        tool_trace = []
        image_paths = []
    else:
        result = await send_message(case["query"])
        answer = result["final_answer"]
        raw_answer = result.get("raw_answer", answer)
        actual_routes = result["route_history"]
        iteration_count = result["iteration_count"]
        tool_trace = result.get("tool_trace", [])
        image_paths = result.get("image_paths", [])
        sensitive_value = case.get("sensitive_value")
        if answer == BLOCKED_MESSAGE:
            actual_guardrail = "blocked"
        elif sensitive_value and sensitive_value not in answer:
            actual_guardrail = "masked"
        else:
            actual_guardrail = "passed"

    route_ok = routes_match(expected_routes, actual_routes)
    guardrail_ok = expected_guardrail == actual_guardrail
    answer_correct = route_ok and guardrail_ok and bool(answer.strip())

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "expected_route": " -> ".join(expected_routes) or "none",
        "actual_route": " -> ".join(actual_routes) or "none",
        "iteration_count": iteration_count,
        "expected_guardrail": expected_guardrail,
        "actual_guardrail": actual_guardrail,
        "answer_correct": answer_correct,
        "what_went_wrong": failure_reason(
            route_ok, guardrail_ok, answer, expected_routes, actual_routes
        ),
        "tool_calls": json.dumps(tool_trace, ensure_ascii=False),
        "image_paths": json.dumps(image_paths, ensure_ascii=False),
        "raw_answer": raw_answer,
        "answer": answer,
    }


async def main() -> None:
    args = parse_args()
    cases = json.loads(QUERIES_FILE.read_text())
    run_directory = create_run_directory(args.run_name)
    run_results_file = run_directory / "results.csv"
    metadata_file = run_directory / "metadata.json"
    started_at = datetime.now(UTC)
    results = []

    metadata = {
        "name": args.run_name,
        "status": "running",
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "score": 0,
        "total": len(cases),
        "models": {
            "supervisor": settings.supervisor_model,
            "guardrails": settings.guardrail_model,
            "rag": settings.rag_model,
            "coding": settings.code_model,
            "cad": settings.visualization_model,
            "general": settings.general_model,
        },
    }
    write_metadata(metadata_file, **metadata)

    try:
        for case in cases:
            try:
                result = await evaluate_case(case)
            except Exception as error:
                result = {
                    "id": case["id"],
                    "category": case["category"],
                    "query": case["query"],
                    "expected_route": " -> ".join(case["expected_routes"]) or "none",
                    "actual_route": "error",
                    "iteration_count": 0,
                    "expected_guardrail": case["expected_guardrail"],
                    "actual_guardrail": "error",
                    "answer_correct": False,
                    "what_went_wrong": f"{type(error).__name__}: {error}",
                    "tool_calls": "[]",
                    "image_paths": "[]",
                    "raw_answer": "",
                    "answer": "",
                }
            results.append(result)
            write_results(results, run_results_file)
            write_results(results, RESULTS_FILE)
            status = "PASS" if result["answer_correct"] else "FAIL"
            print(f"{status}: {result['id']} ({result['actual_route']})", flush=True)
    finally:
        passed = sum(result["answer_correct"] for result in results)
        metadata.update(
            status="completed" if len(results) == len(cases) else "interrupted",
            completed_at=datetime.now(UTC).isoformat(),
            score=passed,
        )
        write_metadata(metadata_file, **metadata)

    print(f"\nScore: {passed}/{len(results)}")
    print(f"Saved run: {run_directory}")


if __name__ == "__main__":
    asyncio.run(main())
