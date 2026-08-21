"""Deterministic comparators for the v2 multi-agent golden dataset."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

PREDICATES = {"ends_with", "min_items", "non_empty"}


def _normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def value_matches(expected: Any, actual: Any) -> bool:
    """Recursively compare a literal/subset or one small predicate object."""

    if isinstance(expected, dict) and set(expected) & PREDICATES:
        if "ends_with" in expected:
            return isinstance(actual, str) and actual.endswith(str(expected["ends_with"]))
        if "min_items" in expected:
            return hasattr(actual, "__len__") and len(actual) >= int(expected["min_items"])
        if "non_empty" in expected:
            return bool(actual) is bool(expected["non_empty"])

    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and value_matches(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                value_matches(left, right) for left, right in zip(expected, actual, strict=True)
            )
        )
    if isinstance(expected, str) and isinstance(actual, str):
        return _normalise_text(expected) == _normalise_text(actual)
    return expected == actual


def call_entries(tool_trace: list[dict]) -> list[dict]:
    return [entry for entry in tool_trace if entry.get("event") == "call"]


def _required_call_matches(spec: dict, call: dict, *, check_arguments: bool) -> bool:
    if spec["tool"] != call.get("tool"):
        return False
    if spec.get("agent") and spec["agent"] != call.get("agent"):
        return False
    if not check_arguments or "arguments" not in spec:
        return True
    return value_matches(spec["arguments"], call.get("arguments", {}))


def compare_tools(expected: dict, tool_trace: list[dict]) -> dict[str, Any]:
    calls = call_entries(tool_trace)
    required = expected.get("required", [])
    forbidden = set(expected.get("forbidden", []))
    actual_names = [call.get("tool", "") for call in calls]

    missing = []
    argument_mismatches = []
    matched_required = 0
    required_total = 0
    for spec in required:
        minimum = int(spec.get("min_count", 1))
        required_total += minimum
        selection_count = sum(
            _required_call_matches(spec, call, check_arguments=False) for call in calls
        )
        matched_required += min(selection_count, minimum)
        if selection_count < minimum:
            missing.append({**spec, "actual_count": selection_count})
        if "arguments" in spec:
            argument_count = sum(
                _required_call_matches(spec, call, check_arguments=True) for call in calls
            )
            if argument_count < minimum:
                argument_mismatches.append({**spec, "matching_argument_count": argument_count})

    forbidden_seen = [name for name in actual_names if name in forbidden]
    ordered = expected.get("ordered_subsequence", [])
    cursor = 0
    for name in actual_names:
        if cursor < len(ordered) and name == ordered[cursor]:
            cursor += 1
    order_correct = cursor == len(ordered)

    return {
        "selection_correct": not missing and not forbidden_seen,
        "arguments_correct": not argument_mismatches,
        "order_correct": order_correct,
        "missing_required": missing,
        "forbidden_seen": forbidden_seen,
        "argument_mismatches": argument_mismatches,
        "required_matched": matched_required,
        "required_total": required_total,
    }


def compare_approvals(expected: dict, actual: list[dict]) -> tuple[bool | None, list[str]]:
    specs = expected.get("approvals")
    if specs is None and "approval" in expected:
        specs = [expected["approval"]]
    if specs is None:
        return None, []

    problems = []
    if len(specs) != len(actual):
        problems.append(f"expected {len(specs)} approval(s), observed {len(actual)}")
    for index, spec in enumerate(specs):
        if index >= len(actual):
            break
        observed = actual[index]
        if spec.get("action") != observed.get("action"):
            problems.append(
                f"approval {index + 1}: expected action {spec.get('action')}, "
                f"got {observed.get('action')}"
            )
        if spec.get("decision") != observed.get("decision"):
            problems.append(
                f"approval {index + 1}: expected decision {spec.get('decision')}, "
                f"got {observed.get('decision')}"
            )
    return not problems, problems


def compare_final(expected: dict, answer: str) -> tuple[bool | None, list[str]]:
    if not expected:
        return None, []
    lowered = answer.lower()
    problems = []
    if expected.get("non_empty") and not answer.strip():
        problems.append("final answer was empty")
    for text in expected.get("contains_all", []):
        if text.lower() not in lowered:
            problems.append(f"final answer did not contain {text!r}")
    for text in expected.get("not_contains", []):
        if text.lower() in lowered:
            problems.append(f"final answer contained forbidden text {text!r}")
    return not problems, problems


def compare_project(expected: dict, project: dict) -> tuple[bool | None, list[str]]:
    if not expected:
        return None, []
    if value_matches(expected, project):
        return True, []
    return False, [
        "project state did not contain expected subset: "
        + json.dumps(expected, ensure_ascii=False, sort_keys=True)
    ]


def _code_reuses_wiring_pins(project: dict) -> tuple[bool, str | None]:
    wiring = project.get("wiring") or {}
    artifact = project.get("code_artifact")
    if not artifact or not Path(artifact).is_file():
        return False, "code artifact was missing"
    assignments = wiring.get("assignments", {})
    pins = {
        str(pin)
        for assignment in assignments.values()
        for pin in assignment.values()
        if pin not in {"5V", "3V3", "VIN", "GND"}
    }
    code = Path(artifact).read_text(encoding="utf-8")
    missing = [
        pin for pin in sorted(pins) if not re.search(rf"(?<!\w){re.escape(pin)}(?!\w)", code)
    ]
    problem = f"generated code did not reuse wiring pin(s): {missing}" if missing else None
    return not missing, problem


def compare_cross_checks(specs: list[dict], project: dict) -> tuple[bool | None, list[str]]:
    if not specs:
        return None, []
    problems = []
    for spec in specs:
        if spec.get("type") == "code_reuses_wiring_pins":
            passed, problem = _code_reuses_wiring_pins(project)
            if not passed and problem:
                problems.append(problem)
        else:
            problems.append(f"unknown cross-check: {spec.get('type')}")
    return not problems, problems


def compare_case(case: dict, execution: dict) -> dict[str, Any]:
    expected = case["expected"]
    actual_routes = execution.get("result", {}).get("route_history", [])
    route_correct = expected.get("routes", []) == actual_routes
    tools = compare_tools(expected.get("tools", {}), execution.get("tool_trace", []))
    approval_correct, approval_problems = compare_approvals(
        expected, execution.get("approvals", [])
    )
    final_correct, final_problems = compare_final(
        expected.get("final", {}), execution.get("answer", "")
    )
    project_correct, project_problems = compare_project(
        expected.get("project", {}), execution.get("result", {}).get("project", {})
    )
    cross_correct, cross_problems = compare_cross_checks(
        expected.get("cross_checks", []), execution.get("result", {}).get("project", {})
    )
    guardrail_correct = expected.get("guardrail") == execution.get("guardrail")
    recovery_correct = None
    recovery_problems = []
    if expected.get("recovery", {}).get("no_uncaught_exception"):
        recovery_correct = execution.get("error") is None
        if not recovery_correct:
            recovery_problems.append("case raised an uncaught exception")

    asserted = [
        route_correct,
        tools["selection_correct"],
        tools["arguments_correct"],
        tools["order_correct"],
        guardrail_correct,
        approval_correct,
        final_correct,
        project_correct,
        cross_correct,
        recovery_correct,
    ]
    case_pass = execution.get("error") is None and all(
        value for value in asserted if value is not None
    )

    failures = []
    if not route_correct:
        failures.append(f"expected routes {expected.get('routes', [])}, got {actual_routes}")
    if not guardrail_correct:
        failures.append(
            f"expected guardrail {expected.get('guardrail')}, got {execution.get('guardrail')}"
        )
    if tools["missing_required"]:
        failures.append(f"missing required tools: {tools['missing_required']}")
    if tools["forbidden_seen"]:
        failures.append(f"forbidden tools called: {tools['forbidden_seen']}")
    if tools["argument_mismatches"]:
        failures.append(f"tool argument mismatches: {tools['argument_mismatches']}")
    if not tools["order_correct"]:
        failures.append("required tool order was not observed")
    failures.extend(approval_problems + final_problems + project_problems + cross_problems)
    failures.extend(recovery_problems)
    if execution.get("error"):
        failures.append(execution["error"])

    return {
        "case_pass": case_pass,
        "route_correct": route_correct,
        "tool_selection_correct": tools["selection_correct"],
        "tool_arguments_correct": tools["arguments_correct"],
        "tool_order_correct": tools["order_correct"],
        "guardrail_correct": guardrail_correct,
        "approval_correct": approval_correct,
        "final_correct": final_correct,
        "project_correct": project_correct,
        "cross_check_correct": cross_correct,
        "recovery_correct": recovery_correct,
        "required_tools_matched": tools["required_matched"],
        "required_tools_total": tools["required_total"],
        "failures": failures,
    }


def aggregate_summary(results: list[dict]) -> dict[str, Any]:
    metric_fields = [
        "case_pass",
        "route_correct",
        "tool_selection_correct",
        "tool_arguments_correct",
        "tool_order_correct",
        "guardrail_correct",
        "approval_correct",
        "final_correct",
        "project_correct",
        "cross_check_correct",
        "recovery_correct",
        "task_completion_correct",
    ]
    metrics = {}
    for field in metric_fields:
        values = [result[field] for result in results if result.get(field) is not None]
        metrics[field] = {
            "passed": sum(bool(value) for value in values),
            "total": len(values),
            "rate": sum(bool(value) for value in values) / len(values) if values else None,
        }

    required_matched = sum(result.get("required_tools_matched", 0) for result in results)
    required_total = sum(result.get("required_tools_total", 0) for result in results)
    route_confusion = Counter(
        (
            " -> ".join(result.get("expected_routes", [])) or "FINISH",
            " -> ".join(result.get("actual_routes", [])) or "FINISH",
        )
        for result in results
    )

    step_ratios = [
        result["step_efficiency_ratio"]
        for result in results
        if result.get("step_efficiency_ratio") is not None
    ]
    costs = [result["cost_usd"] for result in results if result.get("cost_usd") is not None]
    tokens = [
        result["total_tokens"] for result in results if result.get("total_tokens") is not None
    ]
    unpriced_models = sorted(
        {model for result in results for model in result.get("unpriced_models", [])}
    )

    return {
        "cases": len(results),
        "metrics": metrics,
        "required_tool_recall": required_matched / required_total if required_total else None,
        "required_tools_matched": required_matched,
        "required_tools_total": required_total,
        "route_confusion": [
            {"expected": expected, "actual": actual, "count": count}
            for (expected, actual), count in sorted(route_confusion.items())
        ],
        "mean_step_efficiency_ratio": sum(step_ratios) / len(step_ratios) if step_ratios else None,
        "mean_cost_usd": sum(costs) / len(costs) if costs else None,
        "total_cost_usd": sum(costs) if costs else None,
        "mean_total_tokens": sum(tokens) / len(tokens) if tokens else None,
        "unpriced_models": unpriced_models,
    }
