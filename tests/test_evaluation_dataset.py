import json
from collections import Counter
from pathlib import Path

from app.graph import VALID_ROUTES

DATASET = Path("evaluation/golden_dataset/v2/cases.jsonl")
CURRENT_TOOLS = {
    "allocate_pins",
    "answer_question",
    "check_component_availability",
    "create_digikey_proposal",
    "format_wiring_plan",
    "get_board",
    "get_component",
    "get_digikey_order",
    "place_digikey_order",
    "render_openscad",
    "save_code",
    "save_openscad",
    "search_digikey",
    "show_image",
    "validate_code",
    "validate_wiring",
}
RETIRED_TOOLS = {
    "cancel_order",
    "create_purchase_proposal",
    "get_order_status",
    "place_order",
    "suggest_compatible_alternative",
}


def load_cases() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def asserted_tools(case: dict) -> set[str]:
    tools = case["expected"].get("tools", {})
    return (
        {item["tool"] for item in tools.get("required", [])}
        | set(tools.get("forbidden", []))
        | set(tools.get("ordered_subsequence", []))
    )


def test_v2_dataset_has_unique_valid_cases() -> None:
    cases = load_cases()
    ids = [case["id"] for case in cases]

    assert len(cases) == 29
    assert len(ids) == len(set(ids))
    assert all(("query" in case) ^ ("turns" in case) for case in cases)
    assert all(case.get("tags") for case in cases)


def test_v2_covers_every_specialist_and_non_specialist_finish() -> None:
    cases = load_cases()
    route_counts = Counter(
        route for case in cases for route in case["expected"].get("routes", [])
    )

    assert set(route_counts) == VALID_ROUTES - {"FINISH"}
    assert all(route_counts[route] >= 3 for route in route_counts)
    assert any(case["expected"].get("routes") == [] for case in cases)


def test_v2_asserts_only_current_tools() -> None:
    tools = set().union(*(asserted_tools(case) for case in load_cases()))

    assert not tools & RETIRED_TOOLS
    assert tools <= CURRENT_TOOLS


def test_side_effect_rejections_forbid_their_tools() -> None:
    cases = {case["id"]: case for case in load_cases()}

    assert {"save_code", "validate_code"} <= set(
        cases["coding_create_rejected"]["expected"]["tools"]["forbidden"]
    )
    assert {"save_openscad", "render_openscad"} <= set(
        cases["visualization_generic_robot_rejected"]["expected"]["tools"]["forbidden"]
    )
