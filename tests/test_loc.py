from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from indieweb import loc


def test_area_and_directory_buckets() -> None:
    assert loc.area_for_path("src/indieweb/views.py") == "src"
    assert loc.area_for_path("tests/test_views.py") == "tests"
    assert loc.area_for_path("docs/development.rst") == "docs"
    assert loc.area_for_path("examples/custom_consent_template.html") == "examples"
    assert loc.area_for_path("pyproject.toml") == "tooling"

    assert loc.directory_bucket_for_path("src/indieweb/views.py") == "src/indieweb"
    assert loc.directory_bucket_for_path("tests/test_views.py") == "tests"
    assert loc.directory_bucket_for_path("docs/_static/custom.css") == "docs/_static"
    assert loc.directory_bucket_for_path("docs/development.rst") == "docs"
    assert loc.directory_bucket_for_path("justfile") == "."


def test_python_fallback_counts_known_text_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "src" / "indieweb").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src" / "indieweb" / "views.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "__pycache__" / "generated.py").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "tests" / "test_views.py").write_text("def test_example():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
    (tmp_path / ".venv" / "ignored.py").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"not text")

    assert loc._count_with_python(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Overall Summary:" in output
    assert "Python" in output
    assert "TOML" in output
    assert "Repository Overview" in output
    assert "Lines of Code by Directory" in output
    assert ".venv" not in output
    assert "image.png" not in output


def test_excluded_paths_match_nested_generated_directories() -> None:
    assert loc._is_excluded_path(Path(".venv/ignored.py"))
    assert loc._is_excluded_path(Path("src/__pycache__/generated.py"))
    assert loc._is_excluded_path(Path("docs/_build/html/index.html"))
    assert loc._is_excluded_path(Path("frontend/node_modules/package/index.js"))
    assert not loc._is_excluded_path(Path("docs/development.rst"))


def test_cloc_csv_output_is_aggregated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs = iter(
        [
            "language,files,blank,comment,code\nPython,2,3,4,20\nSUM,2,3,4,20\n",
            (
                "language,filename,blank,comment,code\n"
                "Python,src/indieweb/views.py,1,2,10\n"
                "Python,tests/test_views.py,2,2,10\n"
                "SUM,,3,4,20\n"
            ),
        ]
    )

    def fake_run_cloc(command: list[str], root: Path) -> str:
        assert root == tmp_path
        assert command[:2] == ["cloc", "."]
        return next(outputs)

    monkeypatch.setattr(loc, "_run_cloc", fake_run_cloc)

    assert loc._count_with_cloc(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Overall Summary:" in output
    assert "Python" in output
    assert "SUM" in output
    assert "Repository Overview" in output
    assert "src" in output
    assert "tests" in output
    assert "src/indieweb" in output


def test_count_lines_of_code_uses_python_fallback_when_cloc_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(loc.shutil, "which", lambda name: None)

    def fake_count_with_python(root: Path) -> int:
        called["root"] = root
        return 0

    monkeypatch.setattr(loc, "_count_with_python", fake_count_with_python)

    assert loc.count_lines_of_code() == 0
    assert called == {"root": tmp_path}


def test_stats_sort_by_lines_files_then_name() -> None:
    stats = {
        "Beta": {"files": 1, "lines": 10},
        "Alpha": {"files": 1, "lines": 10},
        "Gamma": {"files": 2, "lines": 10},
        "Delta": {"files": 1, "lines": 20},
    }

    assert [name for name, _stats in loc._sort_stats(stats)] == ["Delta", "Gamma", "Alpha", "Beta"]


def test_run_cloc_reports_subprocess_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(7, ["cloc"], stderr="cloc failed\n")

    monkeypatch.setattr(loc.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        loc._run_cloc(["cloc", "."], tmp_path)

    assert exc_info.value.code == 7
    assert capsys.readouterr().err == "cloc failed\n"
