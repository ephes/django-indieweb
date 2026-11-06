"""Smoke tests for the development-only ``example_project.py`` harness."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SMOKE_SCRIPT = """
import json
import sys

sys.path.insert(0, sys.argv[1])
import example_project  # noqa: F401  (configures settings and URLs)

from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.test.utils import setup_test_environment

setup_test_environment()
call_command("migrate", verbosity=0)
response = Client().get("/")
print(json.dumps({
    "status": response.status_code,
    "x_frame_options": response.get("X-Frame-Options"),
    "templates": [t.name for t in response.templates if t.name],
    "middleware": list(settings.MIDDLEWARE),
    "body": response.content.decode(),
}))
"""


def _run_example_project(tmp_path):
    env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
    env["DJANGO_SECRET_KEY"] = "example-project-smoke-test-secret"  # noqa: S105
    env["DJANGO_ALLOWED_HOSTS"] = "testserver"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _SMOKE_SCRIPT, str(REPO_ROOT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_example_project_renders_file_template_with_clickjacking_protection(tmp_path):
    payload = _run_example_project(tmp_path)

    assert payload["status"] == 200
    assert "django.middleware.clickjacking.XFrameOptionsMiddleware" in payload["middleware"]
    assert payload["x_frame_options"] == "DENY"
    assert "example_project/test_page.html" in payload["templates"]
    assert "<title>Test Webmention Page</title>" in payload["body"]
    assert 'rel="webmention"' in payload["body"]
    assert "curl -X POST http://testserver/webmention/ \\\n" in payload["body"]


def test_example_project_has_no_inline_runtime_template():
    source = (REPO_ROOT / "example_project.py").read_text()

    assert "Template(" not in source
    assert (REPO_ROOT / "examples" / "templates" / "example_project" / "test_page.html").is_file()
