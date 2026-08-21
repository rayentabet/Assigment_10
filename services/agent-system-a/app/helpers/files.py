"""Validate files before exposing them as public artifacts."""

from pathlib import Path

from app.config import settings

# tools/model_tools.py and tools/code_tools.py both resolve their own
# "generated" folder the same way, from __file__, rather than from the
# process's working directory: whoever starts the API decides the shell's
# cwd (repo root, per this project's own README, vs. this package's own
# directory in the Docker image), and settings.generated_directory's default
# is a bare relative "generated". Resolving a relative value against cwd
# instead of here would silently point at a directory the specialists never
# write to whenever the process isn't started from this package's own
# directory, so every rendered/generated file would fail this check and
# never reach the client - it happened during local (non-Docker) testing.
APP_ROOT = Path(__file__).resolve().parents[2]


def valid_image(raw_path: str) -> Path | None:
    """Return an approved image path or ``None``."""

    path = Path(raw_path).resolve()
    generated_root = settings.generated_directory
    if not generated_root.is_absolute():
        generated_root = APP_ROOT / generated_root
    roots = [generated_root.resolve(), settings.rag_project_path.resolve()]
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return None
    if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
        return None
    return path
