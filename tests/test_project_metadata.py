import os
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT_DIR = Path(__file__).resolve().parent.parent
MINIMUM_RUNTIME_FLOORS = {
    "django": Version("5.2.13"),
    "httpx": Version("0.28.1"),
    "beautifulsoup4": Version("4.14.2"),
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
