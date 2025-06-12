# Django IndieWeb Project

This is a Django application that implements IndieWeb protocols including IndieAuth and Micropub endpoints.

## Project Structure

- `src/` - Source code directory
  - `indieweb/` - Main Django app module
    - `models.py` - Django models
    - `views.py` - IndieAuth and Micropub endpoint views
    - `urls.py` - URL routing
    - `migrations/` - Database migrations
    - `templates/` - HTML templates
    - `static/` - Static assets

- `tests/` - Test suite
  - `test_auth_endpoint.py` - IndieAuth tests
  - `test_micropub_endpoint.py` - Micropub tests
  - `test_token_endpoint.py` - Token endpoint tests
  - `test_models.py` - Model tests

## Development Setup

This project uses:
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13)
- Django
- uv for packaging and dependency management
- Ruff for linting and formatting (line length: 119)
- Pre-commit hooks for code quality

## Commands

### Testing
```bash
# Run tests
pytest

# Run tests with coverage
coverage run -m pytest tests && coverage html && open htmlcov/index.html

# Run tests with tox
tox
```

### Code Quality
```bash
# Format code with ruff
ruff format .

# Run ruff linting
ruff check .

# Fix linting issues automatically
ruff check --fix .

# Run all pre-commit hooks
pre-commit run --all-files
```

### Documentation
```bash
# Generate Sphinx documentation
make docs
```

### Build & Clean
```bash
# Clean build artifacts
make clean

# Install for development with uv
uv sync
```

### Building & Publishing
```bash
# Build the package
uv build

# Upload to PyPI
uv publish --token your_token
```

## Key Dependencies

- Django
- django-model-utils
- django-braces
- pytz
- setuptools

## Testing Configuration

- Uses pytest with pytest-django
- Database reuse enabled for faster tests
- Migrations disabled during tests
- Django settings: `tests.settings`

## Code Style

- Ruff for linting and formatting with 119 character line length
- Pre-commit hooks for:
  - Trailing whitespace
  - End of file fixing
  - YAML/TOML validation
  - Python upgrades (3.10+)
  - Django upgrades (4.1+)
  - Ruff linting and formatting
  - djhtml for template formatting

## Notes

- Main branch is `develop`
- Documentation at https://django-indieweb.readthedocs.io/
- Source at https://github.com/ephes/django-indieweb
