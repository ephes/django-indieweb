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

# Run type checks with mypy
typecheck:
    uv run mypy

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
    make -C docs clean
    make -C docs html
    uv run python -c "import webbrowser; from pathlib import Path; webbrowser.open(Path('docs/_build/html/index.html').absolute().as_uri())"
