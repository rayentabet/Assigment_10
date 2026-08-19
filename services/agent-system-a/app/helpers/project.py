"""Project-state helpers shared by chat persistence and graph agents."""

import re
from typing import Any

PROJECT_FIELDS = {
    "board",
    "components",
    "wiring",
    "code_artifact",
    "model_artifact",
    "purchase",
    "product_cards",
}


def new_project(saved: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a complete project shape populated from safe known fields."""

    project = {
        "board": None,
        "components": [],
        "wiring": None,
        "code_artifact": None,
        "model_artifact": None,
        "purchase": None,
        "product_cards": [],
    }
    if saved:
        project.update({key: value for key, value in saved.items() if key in PROJECT_FIELDS})
    return project


def pin_map(wiring: dict[str, Any] | None) -> dict[str, dict]:
    """Read assignments from current plans and older component-list plans."""

    if not wiring:
        return {}
    assignments = wiring.get("assignments")
    if isinstance(assignments, dict):
        return assignments
    return {
        item["component"]: item["pins"]
        for item in wiring.get("components", [])
        if isinstance(item, dict) and item.get("component") and isinstance(item.get("pins"), dict)
    }


def wants_rewire(text: str) -> bool:
    """Recognize explicit requests that authorize replacing saved pin assignments."""

    return bool(
        re.search(
            r"\b(rewire|redesign|start over|from scratch|"
            r"replace (?:all|the) wiring|clear wiring)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def project_context(project: dict[str, Any]) -> dict[str, Any]:
    """Return compact project context without purchase credentials or internal tokens."""

    purchase = project.get("purchase")
    if isinstance(purchase, dict):
        purchase = {
            key: value
            for key, value in purchase.items()
            if key not in {"approval_token", "idempotency_key", "proposal"}
        }
    return {
        "board": project.get("board"),
        "components": project.get("components", []),
        "wiring": project.get("wiring"),
        "code_artifact": project.get("code_artifact"),
        "model_artifact": project.get("model_artifact"),
        "purchase": purchase,
        "product_cards": project.get("product_cards", []),
    }
