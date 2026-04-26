# pyupgrade Python 3.14 Hook Failure Investigation

Date: 2026-04-26

## Summary

The `pyupgrade` failure under Python 3.14 is caused by the pinned hook version, not by Python 3.14 being unusable for this project and not by `pre-commit` versus `prek` alone.

The repository had `pyupgrade` pinned to `v3.21.0`. Running that version under Python 3.14 against `docs/conf.py` reproduced the crash:

```text
TypeError: cannot use a bytes pattern on a string-like object
```

Running `pyupgrade==3.21.2` under Python 3.14 against the same file succeeded.

## Commands Tested

```bash
uvx --python 3.14 pyupgrade==3.21.0 --py310-plus --exit-zero-even-if-changed docs/conf.py
uvx --python 3.14 pyupgrade==3.21.2 --py310-plus --exit-zero-even-if-changed docs/conf.py
uvx prek run --all-files
```

With the old hook config, `uvx prek run --all-files` failed in the same way as `pre-commit`, because `prek` also installed and ran the pinned `pyupgrade==3.21.0` hook under Python 3.14.

## Findings

- `pyupgrade v3.21.0` fails under Python 3.14 for at least `docs/conf.py`.
- `pyupgrade v3.21.2` succeeds under Python 3.14 for the same file.
- Switching to `prek` alone does not fix the issue if the hook remains pinned to `v3.21.0`.
- Upgrading the hook revision is the direct fix.
- Pinning hook Python to 3.13 is no longer necessary after upgrading `pyupgrade`.
- `prek` is still a reasonable runner choice for this repo. Its docs say it supports `.pre-commit-config.yaml`, uses `uv` for Python hook environments, and can auto-install Python toolchains based on `language_version`.

## Sources

- pyupgrade release history: https://pypi.org/project/pyupgrade/
- prek language support: https://prek.j178.dev/languages/
- prek differences from pre-commit: https://prek.j178.dev/diff/

## Recommendation

Use `prek` as the hook runner, keep `.pre-commit-config.yaml` for compatibility, and keep hook revisions current. Do not pin hook execution to Python 3.13 unless a future hook breaks on 3.14 again.

Implemented changes:

- Updated `pyupgrade` from `v3.21.0` to `v3.21.2`.
- Updated other hook revisions with `pre-commit autoupdate`.
- Replaced the development dependency `pre-commit` with `prek`.
- Updated docs and tox commands to use `uv run prek run --all-files` / `tox -e hooks`.
