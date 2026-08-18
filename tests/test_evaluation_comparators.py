from evaluation.comparators import (
    aggregate_summary,
    compare_approvals,
    compare_case,
    compare_tools,
    value_matches,
)


def test_value_matches_nested_subset_and_predicates() -> None:
    expected = {
        "artifact": {"ends_with": ".ino"},
        "cards": {"min_items": 1},
        "proposal": {"success": True},
    }
    actual = {
        "artifact": "generated/code/robot.ino",
        "cards": [{"part": "123-ND"}],
        "proposal": {"success": True, "id": "P-1"},
        "ignored": "extra",
    }

    assert value_matches(expected, actual)


def test_compare_tools_scores_selection_arguments_and_order_separately() -> None:
    expected = {
        "required": [
            {"agent": "wiring_agent", "tool": "get_board"},
            {
                "agent": "wiring_agent",
                "tool": "allocate_pins",
                "arguments": {"board": "Arduino Uno"},
            },
        ],
        "ordered_subsequence": ["get_board", "allocate_pins"],
        "forbidden": ["save_code"],
    }
    trace = [
        {"event": "call", "agent": "wiring_agent", "tool": "get_board", "arguments": {}},
        {
            "event": "call",
            "agent": "wiring_agent",
            "tool": "allocate_pins",
            "arguments": {"board": "arduino_uno"},
        },
    ]

    result = compare_tools(expected, trace)

    assert result["selection_correct"] is True
    assert result["arguments_correct"] is True
    assert result["order_correct"] is True


def test_compare_tools_detects_forbidden_and_missing_calls() -> None:
    result = compare_tools(
        {"required": [{"tool": "answer_question"}], "forbidden": ["save_code"]},
        [{"event": "call", "agent": "coding_agent", "tool": "save_code"}],
    )

    assert result["selection_correct"] is False
    assert result["missing_required"]
    assert result["forbidden_seen"] == ["save_code"]


def test_approval_comparator_checks_sequence_and_decision() -> None:
    expected = {
        "approvals": [
            {"action": "coding_agent", "decision": "approved"},
            {"action": "robot_visualization_agent", "decision": "rejected"},
        ]
    }
    actual = [
        {"action": "coding_agent", "decision": "approved"},
        {"action": "robot_visualization_agent", "decision": "rejected"},
    ]

    assert compare_approvals(expected, actual) == (True, [])


def test_compare_case_keeps_route_and_tool_verdicts_independent() -> None:
    case = {
        "expected": {
            "routes": ["rag_agent"],
            "guardrail": "passed",
            "tools": {"required": [{"agent": "rag_agent", "tool": "answer_question"}]},
        }
    }
    execution = {
        "result": {"route_history": ["rag_agent"], "project": {}},
        "answer": "answer",
        "tool_trace": [],
        "approvals": [],
        "guardrail": "passed",
        "error": None,
    }

    result = compare_case(case, execution)

    assert result["route_correct"] is True
    assert result["tool_selection_correct"] is False
    assert result["case_pass"] is False


def test_aggregate_summary_excludes_unasserted_metrics() -> None:
    rows = [
        {
            "case_pass": True,
            "route_correct": True,
            "tool_selection_correct": True,
            "tool_arguments_correct": True,
            "tool_order_correct": True,
            "guardrail_correct": True,
            "approval_correct": None,
            "final_correct": None,
            "project_correct": None,
            "cross_check_correct": None,
            "recovery_correct": None,
            "required_tools_matched": 1,
            "required_tools_total": 1,
            "expected_routes": ["rag_agent"],
            "actual_routes": ["rag_agent"],
        }
    ]

    summary = aggregate_summary(rows)

    assert summary["metrics"]["approval_correct"]["total"] == 0
    assert summary["required_tool_recall"] == 1.0
