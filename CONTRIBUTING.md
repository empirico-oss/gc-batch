# Contributing to gc-batch

Thanks for your interest in contributing. This document covers how to get set up,
what the review expectations are, and how to propose changes. Participation in
this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

`gc-batch` uses [uv](https://docs.astral.sh/uv/) for dependency and environment
management, and [just](https://github.com/casey/just) as a task runner.

```bash
git clone https://github.com/empirico-oss/gc-batch.git
cd gc-batch
uv sync
```

Supported Python versions are 3.10 through 3.13.

## Development workflow

```bash
just test          # run the test suite
just lint          # ruff check, ruff format --check, mypy
just preview-docs  # serve the documentation locally
```

Before opening a pull request, make sure all of the following pass, since CI runs
the same checks:

```bash
uv run pytest -vv tests
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run --group docs mkdocs build --strict
```

These map to the jobs in `.github/workflows/ci.yaml`, which runs on every pull
request and on pushes to `main`: `lint` (ruff), `types` (mypy, blocking), `test`
(pytest on Python 3.10-3.13), `licenses` (runtime dependency licenses stay
MIT-compatible -- `just licenses`), and `docs` (`mkdocs build --strict`, so a
broken link or reference fails the build).

## Building and installing

Released versions are published to [PyPI](https://pypi.org/project/gc-batch/)
and install with `pip install gc-batch`. To test unreleased changes -- or before
the first release lands -- build a wheel locally:

```bash
uv build            # writes dist/gc_batch-<version>-{py3-none-any.whl,.tar.gz}
```

Then install it one of three ways:

```bash
pip install dist/gc_batch-<version>-py3-none-any.whl          # built wheel
uv tool install --force --no-cache ./                          # local checkout
pip install "gc-batch @ git+https://github.com/empirico-oss/gc-batch.git@main"
```

Re-running the `uv tool install` line with `--force` is also how you update an
existing global install. Verify with `gc-batch --version`.

Documentation is published by `.github/workflows/mkdocs.yaml`, which tracks
releases rather than pushes to `main` -- see
[Deploying Documentation](docs/development/docs.md#deploying-documentation). The
`docs` CI job builds the site with `--strict` on every pull request.

## Releasing

`.github/workflows/release.yaml` publishes to PyPI when a GitHub Release is
published. It builds the sdist and wheel, verifies them, and uploads via PyPI
Trusted Publishing, so no API token is stored in the repository.

The release tag is the source of truth for the version: `uv-dynamic-versioning`
derives the version from git, and the workflow refuses to publish if the built
version does not match the tag. To cut a release:

1. Move the pending `CHANGELOG.md` entries under a new version heading.
2. Publish a GitHub Release tagged `v<version>` (for example `v0.1.0`).
3. Approve the `pypi` environment if it is configured to require review.

Dispatch the same workflow manually to publish to TestPyPI first. Run it from a
tag ref, not a branch: off-tag builds carry PEP 440 local version metadata
(`+branch.sha`), which no package index accepts.

Releasing also deploys documentation for that version. The two workflows trigger
deliberately differently -- the release workflow runs for any published release
*including* pre-releases, while the docs workflow runs only for full releases --
so a release candidate reaches PyPI without moving the `stable` docs alias.

## Code standards

- **Type hints are required** on public functions and methods. `mypy` runs over
  `src/` in CI.
- **Formatting and linting** are handled by `ruff` (line length 100). Run
  `uv run ruff format .` to apply formatting.
- **Docstrings** follow the Google style, since the API documentation is generated
  from them by `mkdocstrings`.
- **No deployment-specific values in source.** Project IDs and network
  configuration belong in settings (see below), never hardcoded. This is
  enforced by review.

## Configuration, not hardcoding

Anything that differs between deployments is resolved through `GCBatchSettings`
in `src/gc_batch/settings.py`, with precedence:

1. explicit constructor argument
2. `GC_BATCH_*` environment variables
3. a TOML config file (`--config-file`, `$GC_BATCH_CONFIG_FILE`, `./gc-batch.toml`,
   or `$XDG_CONFIG_HOME/gc-batch/config.toml`)
4. neutral defaults in code

If you are adding a value that varies by environment, add it as a settings field
with a sensible neutral default rather than a literal in the code path. See
[Configuration](docs/guides/configuration.md).

## Tests

- New logic needs tests. Bug fixes should include a test that fails before the fix.
- Tests live in `tests/` and mirror the `src/gc_batch/` layout.
- Avoid tests that require live Google Cloud credentials; mock the client
  boundaries as the existing tests do.

## Pull requests

- Keep pull requests focused on a single concern.
- Describe the motivation, not just the change.
- Call out any breaking change to the CLI surface or the public Python API
  explicitly in the description, and update `CHANGELOG.md`.
- Update the relevant documentation under `docs/` in the same pull request.

## Reporting bugs and requesting features

Open an issue at https://github.com/empirico-oss/gc-batch/issues. For bugs, please include
the `gc-batch` version, your Python version, the command you ran, and the full
error output. Do not include credentials, access tokens, internal project
identifiers, or participant data in issue reports.

For security issues, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.
