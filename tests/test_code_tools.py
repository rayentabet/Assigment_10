from pathlib import Path

import pytest

from tools import code_tools


def test_save_and_validate_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(code_tools, "CODE_FOLDER", tmp_path)

    saved = code_tools.save_code.invoke({"filename": "hello.py", "code": "print('hello')\n"})
    result = code_tools.validate_code.invoke({"filename": "hello.py"})

    assert Path(saved["path"]).is_file()
    assert result["valid"] is True


def test_invalid_python_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(code_tools, "CODE_FOLDER", tmp_path)
    code_tools.save_code.invoke({"filename": "bad.py", "code": "if True print('bad')"})

    result = code_tools.validate_code.invoke({"filename": "bad.py"})

    assert result["valid"] is False


def test_code_path_cannot_contain_folders() -> None:
    with pytest.raises(ValueError, match="without folders"):
        code_tools.code_path("../outside.py")
