---
title: Development Guide
---

# Developing gc-batch

## Development Quick Start

Clone the repository:

```bash title="https"
git clone <repository-url>
cd gc-batch
```

Install dependencies:

```bash
uv sync --group dev
```

Now you can run the CLI in development mode:

```bash
uv run gc-batch --help
```


## Project Structure

```
gc-batch/
├── src/
│   └── gc_batch/
│       ├── __init__.py
│       ├── entrypoint.py    # CLI entry point (Click commands)
│       ├── client.py        # Google Cloud Batch client
│       ├── models/          # Pydantic models
│       │   ├── batch_config.py
│       │   ├── job_request.py
│       │   └── job_result.py
│       ├── google_utils.py  # GCP utilities
│       ├── utils.py         # General utilities
│       └── logger.py        # Logging configuration
├── tests/
│   └── test_gc_batch/
├── docs/                    # Documentation
└── pyproject.toml           # Project configuration
```


## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=gc_batch

# Run specific tests
uv run pytest tests/test_gc_batch/test_utils.py
```


## Code Quality

### Linting and Formatting

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Format code
uv run ruff format

# Check for linting issues
uv run ruff check

# Auto-fix linting issues
uv run ruff check --fix
```

### Type Checking

```bash
uv run mypy src/
```


## Common Development Tasks


### Adding a New Command

Commands are defined in `src/gc_batch/entrypoint.py` using Click:

```python
@cli.command()
@click.option("--my-option", help="Description")
def my_command(my_option: str):
    """Command description."""
    # Implementation
```


### Adding a New Model

Models are Pydantic classes in `src/gc_batch/models/`:

```python
from pydantic import BaseModel


class MyModel(BaseModel):
    field1: str
    field2: int = 0
```


### Working with the Batch Client

The `BatchClient` class in `client.py` wraps the Google Cloud Batch API:

```python
from gc_batch.client import BatchClient

client = BatchClient(project_id="my-project", location="us-central1")
jobs = client.list_jobs()
```


## Regenerating the Lockfile

When you update dependencies in `pyproject.toml`:

```bash
uv lock
```


## Installing for Testing

To install gc-batch globally for testing:

```bash
uv tool install --force --no-cache ./
```

This makes `gc-batch` available system-wide without affecting your development environment.


## Debugging

### Enable Debug Logging

Set the `LOGLEVEL` environment variable:

```bash
LOGLEVEL=DEBUG gc-batch list-jobs
```

### Check GCP Authentication

```bash
gcloud auth list
gcloud config get-value project
```

### Test Batch API Access

```bash
gcloud batch jobs list --location=us-central1
```
