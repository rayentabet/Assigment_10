"""Tools used by the coding agent."""

from pathlib import Path

from langchain_core.tools import tool

PROJECT_FOLDER = Path(__file__).parents[1]
CODE_FOLDER = PROJECT_FOLDER / "generated" / "code"
ALLOWED_EXTENSIONS = {".py", ".ino", ".cpp", ".h", ".js", ".txt"}


def get_code_path(filename: str) -> Path:
    """Return a safe path inside generated/code."""

    if Path(filename).name != filename:
        raise ValueError("Use a filename without folders.")

    path = CODE_FOLDER / filename
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported code file type.")

    return path


@tool
def save_code(filename: str, code: str) -> dict:
    """Save code. Provide a plain filename with extension and the complete code text."""

    path = get_code_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")

    return {"saved": True, "path": str(path)}


@tool
def validate_code(filename: str) -> dict:
    """Validate a saved file using the exact plain filename passed to save_code."""

    path = get_code_path(filename)
    if not path.is_file():
        return {"valid": False, "errors": ["File not found."]}

    code = path.read_text(encoding="utf-8")

    if path.suffix == ".py":
        try:
            compile(code, str(path), "exec")
        except SyntaxError as error:
            return {"valid": False, "errors": [str(error)]}

    if path.suffix in {".ino", ".cpp", ".h", ".js"}:
        if code.count("{") != code.count("}"):
            return {"valid": False, "errors": ["Unbalanced curly brackets."]}

    return {"valid": True, "errors": []}
