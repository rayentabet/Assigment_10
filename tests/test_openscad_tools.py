from pathlib import Path
from subprocess import CompletedProcess

from tools import openscad_tools


def test_save_and_render_openscad(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(openscad_tools, "ROBOT_FOLDER", tmp_path)

    def fake_openscad(command, **kwargs):
        preview_path = Path(command[command.index("-o") + 1])
        preview_path.write_bytes(b"png")
        return CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(openscad_tools.subprocess, "run", fake_openscad)

    saved = openscad_tools.save_openscad.invoke(
        {"model_name": "test robot", "code": "cube([20, 10, 5]);\n"}
    )
    result = openscad_tools.render_openscad.invoke({"model_path": saved["model_path"]})

    assert Path(saved["model_path"]).is_file()
    assert result["success"] is True
    assert Path(result["preview_path"]).is_file()


def test_model_name_is_cleaned() -> None:
    assert openscad_tools.clean_name("my robot") == "my_robot"
