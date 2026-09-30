[private]
default:
  @just --list

# Show available commands
help:
  @echo "Available commands:"
  @echo
  @just --list --unsorted --justfile {{justfile()}}

uv:
  uv sync

test:
  uv run pytest -vv tests

lint:
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src

# Check that runtime dependency licenses stay MIT-compatible
licenses:
  UV_PROJECT_ENVIRONMENT=.venv-licenses uv run --frozen --no-dev python scripts/check_licenses.py

preview-docs *ARGS:
  uv run --only-group docs mkdocs serve {{ ARGS }}
