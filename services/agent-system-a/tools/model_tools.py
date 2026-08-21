"""Tools used by the robot visualization agent.

Parts are structured data (shape, dimensions, position, rotation), not code,
and geometry is built with build123d primitives chosen deterministically from
that data. Unlike the OpenSCAD-based approach this replaces, nothing here
ever executes model-provided text as code or shells out to an external
renderer: it's the same "the model fills in a validated schema, the tool
does the deterministic work" pattern already used by tools/wiring_tools.py.
"""

import json
import math
import re
from pathlib import Path

from build123d import (
    Box,
    BuildPart,
    Compound,
    Cylinder,
    Edge,
    ExportSVG,
    GeomType,
    LineType,
    Locations,
    Sphere,
)
from langchain_core.tools import tool
from PIL import Image, ImageDraw

PROJECT_FOLDER = Path(__file__).parents[1]
ROBOT_FOLDER = PROJECT_FOLDER / "generated" / "robots"

SHAPE_DIMENSIONS = {
    "box": {"length", "width", "height"},
    "cylinder": {"radius", "height"},
    "sphere": {"radius"},
}
MAX_DIMENSION_MM = 2_000
MAX_PARTS = 40

IMAGE_LONG_EDGE = 1_200
IMAGE_MARGIN = 40
CURVE_SAMPLES = 32
DASH_LENGTH_MM = 3.0
# Pillow draws aliased lines, so the raster is built oversized and downsampled.
SUPERSAMPLE = 2


def clean_name(model_name: str) -> str:
    """Convert a model name into a safe folder name."""

    name = re.sub(r"[^a-zA-Z0-9_-]", "_", model_name.strip())
    if not name:
        raise ValueError("Model name cannot be empty.")
    return name


def model_path(model_name: str) -> Path:
    """Return the output path for a model's saved part list."""

    return ROBOT_FOLDER / clean_name(model_name) / "model.json"


def _validate_part(index: int, part: dict) -> str | None:
    """Return an error message for one part, or None if it is well-formed."""

    shape = part.get("shape")
    if shape not in SHAPE_DIMENSIONS:
        return f"part {index}: shape must be one of {sorted(SHAPE_DIMENSIONS)}, got {shape!r}"

    dimensions = part.get("dimensions")
    if not isinstance(dimensions, dict):
        return f"part {index}: dimensions must be an object"

    required = SHAPE_DIMENSIONS[shape]
    missing = required - dimensions.keys()
    if missing:
        return f"part {index}: {shape} is missing dimensions {sorted(missing)}"

    for key in required:
        value = dimensions[key]
        if not isinstance(value, int | float) or isinstance(value, bool):
            return f"part {index}: dimensions.{key} must be a number"
        if not (0 < value <= MAX_DIMENSION_MM):
            return f"part {index}: dimensions.{key} must be between 0 and {MAX_DIMENSION_MM}mm"

    for field in ("position", "rotation"):
        value = part.get(field, [0, 0, 0])
        if not (isinstance(value, list) and len(value) == 3):
            return f"part {index}: {field} must be [x, y, z]"
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
            return f"part {index}: {field} values must be numbers"

    return None


@tool
def save_model(model_name: str, parts: list[dict]) -> dict:
    """Save a robot's parts as a validated model.

    Each part is an object: shape ("box" | "cylinder" | "sphere"), dimensions
    in millimeters (box: length/width/height, cylinder: radius/height,
    sphere: radius), and optional position [x, y, z] and rotation
    [x, y, z] in degrees (both default to [0, 0, 0]).
    """

    if not parts:
        return {"saved": False, "model_path": None, "errors": ["parts must not be empty."]}
    if len(parts) > MAX_PARTS:
        error = f"Too many parts (max {MAX_PARTS})."
        return {"saved": False, "model_path": None, "errors": [error]}

    errors = [error for index, part in enumerate(parts) if (error := _validate_part(index, part))]
    if errors:
        return {"saved": False, "model_path": None, "errors": errors}

    path = model_path(model_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"parts": parts}, indent=2), encoding="utf-8")

    return {"saved": True, "model_path": str(path), "errors": []}


def _build_part(part: dict) -> None:
    """Add one part to the currently open BuildPart context."""

    shape = part["shape"]
    dimensions = part["dimensions"]
    position = tuple(part.get("position", [0, 0, 0]))
    rotation = tuple(part.get("rotation", [0, 0, 0]))

    with Locations(position):
        if shape == "box":
            Box(dimensions["length"], dimensions["width"], dimensions["height"], rotation=rotation)
        elif shape == "cylinder":
            Cylinder(dimensions["radius"], dimensions["height"], rotation=rotation)
        else:
            Sphere(dimensions["radius"], rotation=rotation)


def _resolved_model_path(model_path: str) -> Path:
    """Return a saved model's path, rejecting anything outside generated/robots."""

    path = Path(model_path).resolve()

    if ROBOT_FOLDER.resolve() not in path.parents or path.suffix != ".json":
        raise ValueError("Model must be a .json file inside generated/robots.")
    if not path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")
    return path


def _build_compound(path: Path) -> Compound:
    parts = json.loads(path.read_text(encoding="utf-8"))["parts"]
    with BuildPart() as builder:
        for part in parts:
            _build_part(part)
    return builder.part


def _project_isometric(compound: Compound) -> tuple[list[Edge], list[Edge]]:
    """Project a model onto an isometric viewport as visible and hidden edges."""

    bounding_box = compound.bounding_box()
    diagonal = math.sqrt(sum(component**2 for component in bounding_box.size))
    distance = max(diagonal * 1.5, 100.0)
    center = bounding_box.center()
    offset = distance / math.sqrt(3)
    viewport_origin = (center.X + offset, center.Y - offset, center.Z + offset)
    return compound.project_to_viewport(viewport_origin)


def _failure(path: Path, message: str) -> dict:
    return {
        "success": False,
        "model_path": str(path),
        "preview_path": None,
        "vector_path": None,
        "rendering_errors": [message],
    }


def _write_svg(visible: list[Edge], hidden: list[Edge], destination: Path) -> None:
    exporter = ExportSVG(scale=4, line_weight=0.5)
    exporter.add_layer("Visible")
    exporter.add_layer("Hidden", line_color=(160, 160, 160), line_type=LineType.DASHED)
    exporter.add_shape(visible, layer="Visible")
    exporter.add_shape(hidden, layer="Hidden")
    exporter.write(str(destination))


@tool
def render_model(model_path: str) -> dict:
    """Render a saved model as an isometric preview with hidden lines dashed.

    Writes two files next to the model: preview.png, the picture shown to the
    user, and preview.svg, the same view as scalable vector artwork.
    """

    try:
        path = _resolved_model_path(model_path)
    except (ValueError, FileNotFoundError) as error:
        return _failure(Path(model_path), str(error))
    preview_path = path.with_name("preview.png")
    vector_path = path.with_name("preview.svg")

    try:
        compound = _build_compound(path)
    except Exception as error:  # noqa: BLE001 - report as a normal tool failure
        return _failure(path, f"Geometry construction failed: {error}")

    try:
        visible, hidden = _project_isometric(compound)
    except Exception as error:  # noqa: BLE001 - report as a normal tool failure
        return _failure(path, f"Projection failed: {error}")

    try:
        _draw_preview(visible, hidden).save(preview_path)
    except Exception as error:  # noqa: BLE001 - report as a normal tool failure
        return _failure(path, f"Picture export failed: {error}")

    # The picture is what the user sees, so a failed SVG is reported alongside a
    # successful render rather than discarding the preview that already worked.
    errors = []
    try:
        _write_svg(visible, hidden, vector_path)
    except Exception as error:  # noqa: BLE001 - report as a normal tool failure
        errors.append(f"SVG export failed: {error}")

    return {
        "success": preview_path.is_file(),
        "model_path": str(path),
        "preview_path": str(preview_path) if preview_path.is_file() else None,
        "vector_path": str(vector_path) if vector_path.is_file() else None,
        "rendering_errors": errors
        if preview_path.is_file()
        else [*errors, "PNG export did not create a file."],
    }


def _edge_polyline(edge: Edge) -> list[tuple[float, float]]:
    """Flatten one projected edge into 2D points, subdividing curves."""

    samples = 1 if edge.geom_type == GeomType.LINE else CURVE_SAMPLES
    points = []
    for step in range(samples + 1):
        point = edge @ (step / samples)
        points.append((point.X, point.Y))
    return points


def _dashed_runs(points: list[tuple[float, float]], dash: float) -> list[list[tuple[float, float]]]:
    """Split a polyline into the drawn pieces of a dashed line."""

    runs: list[list[tuple[float, float]]] = []
    run: list[tuple[float, float]] = []
    travelled = 0.0

    for start, end in zip(points, points[1:], strict=False):
        length = math.dist(start, end)
        if not length:
            continue
        position = 0.0
        while position < length:
            step = min(dash - travelled % dash, length - position)
            head = _interpolate(start, end, position / length)
            tail = _interpolate(start, end, (position + step) / length)
            if int(travelled // dash) % 2 == 0:
                run = run or [head]
                run.append(tail)
            elif run:
                runs.append(run)
                run = []
            position += step
            travelled += step

    if run:
        runs.append(run)
    return runs


def _interpolate(
    start: tuple[float, float], end: tuple[float, float], fraction: float
) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )


def _draw_preview(visible: list[Edge], hidden: list[Edge]) -> Image.Image:
    """Draw projected edges into an anti-aliased raster preview."""

    hidden_lines = [_edge_polyline(edge) for edge in hidden]
    visible_lines = [_edge_polyline(edge) for edge in visible]
    all_points = [point for line in hidden_lines + visible_lines for point in line]
    if not all_points:
        raise ValueError("The projection produced no edges to draw.")

    min_x = min(x for x, _ in all_points)
    max_x = max(x for x, _ in all_points)
    min_y = min(y for _, y in all_points)
    max_y = max(y for _, y in all_points)
    span = max(max_x - min_x, max_y - min_y) or 1.0
    scale = (IMAGE_LONG_EDGE - 2 * IMAGE_MARGIN) / span * SUPERSAMPLE
    margin = IMAGE_MARGIN * SUPERSAMPLE
    width = round((max_x - min_x) * scale) + 2 * margin
    height = round((max_y - min_y) * scale) + 2 * margin

    def to_pixels(line):
        # Image rows grow downward, so the model's +Y is flipped.
        return [
            (margin + (x - min_x) * scale, height - margin - (y - min_y) * scale) for x, y in line
        ]

    image = Image.new("RGB", (width, height), "white")
    canvas = ImageDraw.Draw(image)
    for line in hidden_lines:
        for run in _dashed_runs(line, DASH_LENGTH_MM):
            canvas.line(to_pixels(run), fill=(160, 160, 160), width=SUPERSAMPLE)
    for line in visible_lines:
        canvas.line(to_pixels(line), fill=(20, 20, 20), width=2 * SUPERSAMPLE)

    return image.resize((width // SUPERSAMPLE, height // SUPERSAMPLE), Image.LANCZOS)
