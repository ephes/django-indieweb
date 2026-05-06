# Agent Learnings

This file holds concise, reviewed, repo-specific lessons for future agent work.
It is not a session log, transcript archive, prompt collection, or command-output
dump.

## Privacy Boundary

- Do not paste raw transcripts, prompts, command output, generated summaries, or
  private local context into this file.
- Keep private session material in the gitignored paths listed in `.gitignore`
  and `AGENTS.md`, such as `.agent-summaries/`, `.agent-transcripts/`,
  `codex-session-*.md`, and `claude-session-*.md`.

## Current Learnings

- Treat `BACKLOG.md` and `DONE.md` as the project plan. Completing a backlog
  item means removing it from `BACKLOG.md` and adding a dated `DONE.md` entry
  with validation, documentation, and changelog notes. If documentation or a
  changelog update is not needed, say that explicitly.
- Validate Sphinx docs without staging generated output. Use
  `uv run sphinx-build -W -b html docs docs/_build/html`, and check
  `git ls-files docs/_build --modified --others --exclude-standard`; it should
  print nothing.
- Use `prek`, not `pre-commit`, for configured hooks. The normal command is
  `uv run prek run --all-files`; the tox hook environment is `tox -e hooks`.
- New tests should use pytest function/fixture style. Do not mix
  `pytest.mark.parametrize` into legacy `django.test.TestCase` classes; convert
  those files in focused maintenance slices.
- Keep host-owned protocol boundaries explicit. Optional integrations and
  examples such as Webmention.io display/import, Microsub or reader behavior,
  WebSub delivery processing, static-site storage, media indexes, and
  syndication targets should not be described as django-indieweb core behavior
  unless the package actually ships that behavior.

## Updating This File

- Add a learning only when a repeated repo-specific issue is supported by
  reviewed project history, such as `DONE.md`, documentation audits, or review
  feedback.
- Prefer a short actionable bullet over a broad rule copied from `AGENTS.md`.
- Do not add generic agent advice or one-off personal notes.
