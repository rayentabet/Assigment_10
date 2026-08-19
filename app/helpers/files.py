"""Validate files before exposing them as public artifacts."""

from pathlib import Path

from app.config import settings


def valid_image(raw_path: str) -> Path | None:
    """Return an approved image path or ``None``."""

    path = Path(raw_path).resolve()
    roots = [settings.generated_directory.resolve(), settings.rag_project_path.resolve()]
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return None
    if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
        return None
    return path
