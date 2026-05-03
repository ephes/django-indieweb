from __future__ import annotations

import csv
import io
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TypedDict


class ClocSummaryRow(TypedDict):
    language: str
    files: int
    blank: int
    comment: int
    code: int


class StatsRow(TypedDict):
    files: int
    lines: int


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "docs/_build",
    "htmlcov",
    "node_modules",
}
LANGUAGE_BY_NAME = {
    ".coveragerc": "INI",
    ".editorconfig": "INI",
    ".envrc": "Shell",
    ".flake8": "INI",
    ".gitattributes": "Git Attributes",
    ".gitignore": "Gitignore",
    "Dockerfile": "Dockerfile",
    "justfile": "Justfile",
    "LICENSE": "Text",
    "Makefile": "Makefile",
    "MANIFEST.in": "Manifest",
}
LANGUAGE_BY_SUFFIX = {
    ".cfg": "INI",
    ".css": "CSS",
    ".html": "HTML",
    ".in": "Manifest",
    ".ini": "INI",
    ".js": "JavaScript",
    ".lock": "TOML",
    ".md": "Markdown",
    ".py": "Python",
    ".rst": "reStructuredText",
    ".toml": "TOML",
    ".txt": "Text",
    ".yaml": "YAML",
    ".yml": "YAML",
}


def count_lines_of_code() -> int:
    root = Path.cwd()
    if shutil.which("cloc"):
        return _count_with_cloc(root)

    print("cloc not found, using Python fallback.", file=sys.stderr)
    return _count_with_python(root)


def _count_with_cloc(root: Path) -> int:
    summary_output = _run_cloc(
        [
            "cloc",
            ".",
            "--vcs=git",
            "--csv",
            "--quiet",
        ],
        root,
    )
    detail_output = _run_cloc(
        [
            "cloc",
            ".",
            "--vcs=git",
            "--by-file",
            "--csv",
            "--quiet",
        ],
        root,
    )
    summary_rows = _parse_cloc_summary_csv(summary_output)
    area_stats, directory_stats = _aggregate_cloc_file_csv(detail_output)

    print("Overall Summary:")
    print(_render_cloc_summary_table(summary_rows))
    print()
    print(_render_area_table(area_stats))
    print()
    print(_render_directory_table(directory_stats))
    return 0


def _count_with_python(root: Path) -> int:
    language_stats: dict[str, StatsRow] = defaultdict(_stats_row)
    area_stats: dict[str, StatsRow] = defaultdict(_stats_row)
    directory_stats: dict[str, StatsRow] = defaultdict(_stats_row)

    for relative_path in _iter_fallback_paths(root):
        language = _language_for_path(relative_path)
        if language is None:
            continue

        try:
            with (root / relative_path).open(encoding="utf-8", errors="ignore") as handle:
                line_count = sum(1 for _ in handle)
        except OSError as exc:
            print(f"Warning: could not read {relative_path}: {exc}", file=sys.stderr)
            continue

        area = area_for_path(relative_path)
        directory = directory_bucket_for_path(relative_path)
        _add_stats(language_stats[language], line_count)
        _add_stats(area_stats[area], line_count)
        _add_stats(directory_stats[directory], line_count)

    print("Overall Summary:")
    print(_render_language_summary_table(dict(language_stats)))
    print()
    print(_render_area_table(dict(area_stats)))
    print()
    print(_render_directory_table(dict(directory_stats)))
    return 0


def _run_cloc(command: Sequence[str], root: Path) -> str:
    try:
        result = subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        if stderr:
            print(stderr, file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
    return result.stdout


def _parse_cloc_summary_csv(csv_output: str) -> list[ClocSummaryRow]:
    rows: list[ClocSummaryRow] = []
    for row in csv.DictReader(io.StringIO(csv_output)):
        language = row.get("language", "").strip()
        if not language:
            continue
        # cloc includes a SUM row in summary output; keep it for the language table total.
        try:
            rows.append(
                {
                    "language": language,
                    "files": int(row["files"]),
                    "blank": int(row["blank"]),
                    "comment": int(row["comment"]),
                    "code": int(row["code"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def _aggregate_cloc_file_csv(csv_output: str) -> tuple[dict[str, StatsRow], dict[str, StatsRow]]:
    area_stats: dict[str, StatsRow] = defaultdict(_stats_row)
    directory_stats: dict[str, StatsRow] = defaultdict(_stats_row)

    for row in csv.DictReader(io.StringIO(csv_output)):
        file_path = row.get("filename", "").strip()
        if not file_path or file_path == "SUM":
            continue
        try:
            line_count = int(row["code"])
        except (KeyError, TypeError, ValueError):
            continue

        area = area_for_path(file_path)
        directory = directory_bucket_for_path(file_path)
        _add_stats(area_stats[area], line_count)
        _add_stats(directory_stats[directory], line_count)

    return dict(area_stats), dict(directory_stats)


def area_for_path(path: str | Path) -> str:
    parts = _normalized_parts(path)
    if not parts:
        return "tooling"
    if _is_test_path(parts):
        return "tests"
    if parts[0] == "src":
        return "src"
    if parts[0] == "docs":
        return "docs"
    if parts[0] in {"examples", "specs"}:
        return parts[0]
    return "tooling"


def directory_bucket_for_path(path: str | Path) -> str:
    parts = _normalized_parts(path)
    if not parts:
        return "."
    if parts[0] == "src" and len(parts) >= 2:
        return f"src/{parts[1]}"
    if parts[0] == "tests":
        return "tests"
    if parts[0] == "docs" and len(parts) >= 2:
        return f"docs/{parts[1]}" if parts[1].startswith("_") else "docs"
    return parts[0] if len(parts) > 1 else "."


def _iter_fallback_paths(root: Path) -> Iterable[Path]:
    git_paths = _git_tracked_paths(root)
    if git_paths:
        yield from (path for path in git_paths if not _is_excluded_path(path))
        return

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if not _is_excluded_path(relative_path):
            yield relative_path


def _git_tracked_paths(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(part.decode()) for part in result.stdout.split(b"\0") if part]


def _is_excluded_path(path: Path) -> bool:
    parts = _normalized_parts(path)
    excluded_names = {entry for entry in EXCLUDED_DIRS if "/" not in entry}
    if any(part in excluded_names for part in parts):
        return True

    excluded_paths = {entry for entry in EXCLUDED_DIRS if "/" in entry}
    for index in range(len(parts)):
        if "/".join(parts[: index + 1]) in excluded_paths:
            return True
    return False


def _language_for_path(path: Path) -> str | None:
    if path.name in LANGUAGE_BY_NAME:
        return LANGUAGE_BY_NAME[path.name]
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def _normalized_parts(path: str | Path) -> tuple[str, ...]:
    return tuple(part for part in Path(path).parts if part not in {"", "."})


def _is_test_path(parts: tuple[str, ...]) -> bool:
    if "tests" in parts:
        return True
    name = parts[-1] if parts else ""
    return name.startswith("test_") or name.endswith("_test.py") or ".test." in name or ".spec." in name


def _stats_row() -> StatsRow:
    return {"files": 0, "lines": 0}


def _add_stats(row: StatsRow, line_count: int) -> None:
    row["files"] += 1
    row["lines"] += line_count


def _render_language_summary_table(language_stats: dict[str, StatsRow]) -> str:
    rows = []
    total_files = 0
    total_lines = 0
    for language, stats in _sort_stats(language_stats):
        rows.append((language, str(stats["files"]), str(stats["lines"])))
        total_files += stats["files"]
        total_lines += stats["lines"]
    rows.append(("SUM", str(total_files), str(total_lines)))
    return _render_table(("Language", "Files", "Lines"), rows)


def _render_cloc_summary_table(rows: Sequence[ClocSummaryRow]) -> str:
    rendered_rows = [
        (row["language"], str(row["files"]), str(row["blank"]), str(row["comment"]), str(row["code"])) for row in rows
    ]
    return _render_table(("Language", "Files", "Blank", "Comment", "Code"), rendered_rows)


def _render_area_table(area_stats: dict[str, StatsRow]) -> str:
    total_lines = sum(stats["lines"] for stats in area_stats.values())
    rows = [
        (area, str(stats["files"]), str(stats["lines"]), _format_share(stats["lines"], total_lines))
        for area, stats in _sort_stats(area_stats)
    ]
    return _render_table(("Area", "Files", "Lines", "Share"), rows, title="Repository Overview")


def _render_directory_table(directory_stats: dict[str, StatsRow]) -> str:
    rows = [(directory, str(stats["files"]), str(stats["lines"])) for directory, stats in _sort_stats(directory_stats)]
    return _render_table(("Directory", "Files", "Lines"), rows, title="Lines of Code by Directory")


def _sort_stats(stats_by_key: dict[str, StatsRow]) -> list[tuple[str, StatsRow]]:
    return sorted(
        stats_by_key.items(),
        key=lambda item: (-item[1]["lines"], -item[1]["files"], item[0]),
    )


def _format_share(lines: int, total_lines: int) -> str:
    if total_lines == 0:
        return "0.0%"
    return f"{(lines / total_lines) * 100:5.1f}%"


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], title: str | None = None) -> str:
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    output = []
    if title:
        output.append(title)
    output.append(border)
    output.append(
        "| "
        + " | ".join(
            header.ljust(widths[index]) if index == 0 else header.rjust(widths[index])
            for index, header in enumerate(headers)
        )
        + " |"
    )
    output.append(border)
    for row in rows:
        output.append(
            "| "
            + " | ".join(
                value.ljust(widths[index]) if index == 0 else value.rjust(widths[index])
                for index, value in enumerate(row)
            )
            + " |"
        )
    output.append(border)
    return "\n".join(output)
