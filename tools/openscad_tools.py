"""Tools used by the robot visualization agent."""

import re
import subprocess
from pathlib import Path

from langchain_core.tools import tool

PROJECT_FOLDER = Path(__file__).parents[1]
ROBOT_FOLDER = PROJECT_FOLDER / "generated" / "robots"


def clean_name(model_name: str) -> str:
    """Convert a model name into a safe folder name."""

    name = re.sub(r"[^a-zA-Z0-9_-]", "_", model_name.strip())
    if not name:
        raise ValueError("Model name cannot be empty.")
    return name


def get_model_path(model_name: str) -> Path:
    """Return the output path for an OpenSCAD model."""

    return ROBOT_FOLDER / clean_name(model_name) / "model.scad"


@tool
def save_openscad(model_name: str, code: str) -> dict:
    """Save OpenSCAD code as a .scad file."""

    path = get_model_path(model_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")

    return {"saved": True, "model_path": str(path)}


@tool
def render_openscad(model_path: str) -> dict:
    """Render a saved OpenSCAD model as a PNG preview."""

    path = Path(model_path).resolve()
    robot_folder = ROBOT_FOLDER.resolve()

    if robot_folder not in path.parents or path.suffix != ".scad":
        raise ValueError("Model must be a .scad file inside generated/robots.")
    if not path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")

    preview_path = path.with_name("preview.png")
    command = [
        "openscad",
        "--render",
        "--autocenter",
        "--viewall",
        "--imgsize=1200,900",
        "-o",
        str(preview_path),
        str(path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "model_path": str(path),
            "preview_path": None,
            "rendering_errors": ["OpenSCAD is not installed."],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "model_path": str(path),
            "preview_path": None,
            "rendering_errors": ["Rendering took longer than 60 seconds."],
        }

    errors = []
    if result.returncode != 0:
        errors.append(result.stderr.strip() or "OpenSCAD rendering failed.")
    if not preview_path.is_file():
        errors.append("OpenSCAD did not create a preview image.")

    return {
        "success": not errors,
        "model_path": str(path),
        "preview_path": str(preview_path) if preview_path.is_file() else None,
        "rendering_errors": errors,
    }
