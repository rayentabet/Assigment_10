from pathlib import Path

from PIL import Image

from tools import model_tools


def test_save_and_render_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(model_tools, "ROBOT_FOLDER", tmp_path)

    parts = [
        {"shape": "box", "dimensions": {"length": 60, "width": 40, "height": 15}},
        {
            "shape": "cylinder",
            "dimensions": {"radius": 15, "height": 6},
            "position": [-20, 0, 0],
            "rotation": [90, 0, 0],
        },
    ]

    saved = model_tools.save_model.invoke({"model_name": "test robot", "parts": parts})
    assert saved["saved"] is True
    assert Path(saved["model_path"]).is_file()

    result = model_tools.render_model.invoke({"model_path": saved["model_path"]})

    assert result["success"] is True
    assert result["rendering_errors"] == []

    # preview_path is the picture shown in chat; the SVG is a side artifact.
    preview = Path(result["preview_path"])
    vector = Path(result["vector_path"])
    assert preview.is_file() and preview.suffix == ".png"
    assert vector.is_file() and vector.suffix == ".svg"

    with Image.open(preview) as image:
        assert image.format == "PNG"
        assert min(image.size) > 0


def test_save_model_rejects_missing_dimensions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(model_tools, "ROBOT_FOLDER", tmp_path)

    result = model_tools.save_model.invoke(
        {
            "model_name": "bad robot",
            "parts": [{"shape": "box", "dimensions": {"length": 10, "width": 10}}],
        }
    )

    assert result["saved"] is False
    assert "height" in result["errors"][0]


def test_save_model_rejects_unknown_shape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(model_tools, "ROBOT_FOLDER", tmp_path)

    result = model_tools.save_model.invoke(
        {"model_name": "bad robot", "parts": [{"shape": "cone", "dimensions": {}}]}
    )

    assert result["saved"] is False
    assert "shape" in result["errors"][0]


def test_save_model_rejects_empty_parts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(model_tools, "ROBOT_FOLDER", tmp_path)

    result = model_tools.save_model.invoke({"model_name": "empty robot", "parts": []})

    assert result["saved"] is False
    assert result["model_path"] is None


def test_render_model_rejects_path_outside_robot_folder(tmp_path: Path, monkeypatch) -> None:
    # render_model must degrade to a normal tool failure, not raise, for any
    # bad path (invalid path, missing file, wrong extension): it runs inside
    # an agent loop, and an uncaught exception here crashes the whole turn
    # instead of letting the model see the error and respond.
    monkeypatch.setattr(model_tools, "ROBOT_FOLDER", tmp_path / "robots")
    outside = tmp_path / "elsewhere" / "model.json"
    outside.parent.mkdir(parents=True)
    outside.write_text('{"parts": []}', encoding="utf-8")

    result = model_tools.render_model.invoke({"model_path": str(outside)})

    assert result["success"] is False
    assert "generated/robots" in result["rendering_errors"][0]


def test_model_name_is_cleaned() -> None:
    assert model_tools.clean_name("my robot") == "my_robot"
