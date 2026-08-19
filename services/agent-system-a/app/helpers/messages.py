"""Normalize agent messages and structured tool results."""

import ast
import json
from pathlib import Path
from typing import Any

from app.config import settings


def to_text(content: Any) -> str:
    """Flatten a model reply into displayable text."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif not isinstance(item, dict):
                parts.append(str(item))
        return "\n\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def extract_images(value: Any) -> list[str]:
    """Find image and preview paths in nested tool output."""

    if isinstance(value, dict):
        paths = []
        for key, item in value.items():
            if key in {"image_path", "preview_path"} and item:
                path = Path(str(item))
                if not path.is_absolute():
                    path = settings.rag_project_path / path
                paths.append(str(path.resolve()))
            else:
                paths.extend(extract_images(item))
        return paths
    if isinstance(value, list):
        return [path for item in value for path in extract_images(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
        return [] if parsed == value else extract_images(parsed)
    return []


def extract_result(messages: list, tool_name: str) -> dict | None:
    """Return the latest structured result for one tool."""

    result = None
    for message in messages:
        if message.type != "tool" or getattr(message, "name", None) != tool_name:
            continue
        content = message.content
        if isinstance(content, dict):
            result = content
            continue
        if not isinstance(content, str):
            continue
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = ast.literal_eval(content)
            except (ValueError, SyntaxError):
                continue
        if isinstance(parsed, dict):
            result = parsed
    return result


def merge_results(results: list[dict[str, Any]]) -> str:
    """Combine specialist answers without exposing agent metadata."""

    return "\n\n".join(item["result"] for item in results)
