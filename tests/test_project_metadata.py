import os
import subprocess
import sys
import tomllib
from configparser import ConfigParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT_DIR = Path(__file__).resolve().parent.parent
MINIMUM_RUNTIME_FLOORS = {
    "django": Version("5.2.13"),
    "httpx": Version("0.28.1"),
    "beautifulsoup4": Version("4.15.0"),
    "soupsieve": Version("4.1"),
    "mf2py": Version("2.0.1"),
    "cryptography": Version("50.0.0"),
}


def _declares_floor_at_or_above(specifier: SpecifierSet, minimum: Version) -> bool:
    for spec in specifier:
        if spec.operator not in {">=", "~="}:
            continue
        if Version(spec.version) >= minimum:
            return True
    return False


def test_runtime_dependency_floors_are_declared() -> None:
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())
    dependencies = {
        Requirement(dependency).name.lower(): Requirement(dependency).specifier
        for dependency in pyproject["project"]["dependencies"]
    }

    for dependency_name, minimum_floor in MINIMUM_RUNTIME_FLOORS.items():
        assert dependency_name in dependencies
        assert _declares_floor_at_or_above(dependencies[dependency_name], minimum_floor)


def test_uv_lockfile_is_tracked_for_reproducible_releases() -> None:
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", "uv.lock"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )


def test_python_floor_supports_patched_runtime_selector() -> None:
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())
    supported = SpecifierSet(pyproject["project"]["requires-python"])

    assert Version("3.11.4") not in supported
    assert Version("3.11.5") in supported


def test_locked_selector_includes_security_fix() -> None:
    lock = tomllib.loads((ROOT_DIR / "uv.lock").read_text())
    selectors = [package for package in lock["package"] if package["name"] == "soupsieve"]

    assert selectors
    assert all(Version(package["version"]) >= Version("4.1") for package in selectors)


def test_readthedocs_installs_project_runtime_dependencies() -> None:
    config = (ROOT_DIR / ".readthedocs.yml").read_text()

    assert "    - method: pip\n      path: .\n" in config


def test_test_settings_secret_key_uses_sentinel_default() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_INDIEWEB_TEST_SECRET_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "import tests.settings; print(tests.settings.SECRET_KEY)"],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "insecure-test-key-do-not-use"


def test_test_settings_secret_key_can_be_loaded_from_environment() -> None:
    env = os.environ.copy()
    env["DJANGO_INDIEWEB_TEST_SECRET_KEY"] = "local-test-secret"
    result = subprocess.run(
        [sys.executable, "-c", "import tests.settings; print(tests.settings.SECRET_KEY)"],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "local-test-secret"


def test_tox_has_migration_enabled_test_environment() -> None:
    tox_config = ConfigParser()
    tox_config.read(ROOT_DIR / "tox.ini")

    envlist = tox_config["tox"]["envlist"]
    commands = tox_config["testenv:py313-django52-migrations"]["commands"]

    assert "py313-django52-migrations" in envlist
    assert "pytest --migrations --no-cov" in commands
