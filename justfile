# Justfile for django-indieweb project development

# Default recipe - show available commands
default:
    @just --list

# Install Python dependencies via uv
install:
    uv sync

# Run the full test suite
test:
    uv run pytest

# Run a specific test (pass path or node id)
test-one TARGET:
    uv run pytest {{TARGET}} -v

# Run lint, typecheck, and tests
check:
    just lint
    just typecheck
    just test

# Run linting and formatting with ruff
lint:
    uv run ruff check --fix .
    uv run ruff format .

# Run type checks with mypy
typecheck:
    uv run mypy

# Run configured repository hooks
hooks:
    uv run prek run --all-files

# Count repository lines with language, area, and directory summaries
loc:
    @uv run count-lines-of-code

# Generate a CycloneDX SBOM from the locked runtime dependency graph
sbom:
    mkdir -p dist
    uv export --format cyclonedx1.5 --preview-features sbom-export --frozen --no-dev > dist/django-indieweb-sbom.cdx.json

# Remove build artifacts
clean-build:
    rm -fr build/
    rm -fr dist/
    rm -fr *.egg-info

# Remove Python file artifacts
clean-pyc:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +

# Remove all build and Python artifacts
clean: clean-build clean-pyc

# Generate Sphinx HTML documentation and open in browser
docs:
    rm -f docs/django-indieweb.rst
    rm -f docs/modules.rst
    uv run sphinx-apidoc -o docs/ src/indieweb "**/migrations/*"
    rm -rf docs/_build/html
    uv run sphinx-build -W -b html docs docs/_build/html
    uv run python -c "import webbrowser; from pathlib import Path; webbrowser.open(Path('docs/_build/html/index.html').absolute().as_uri())"
