# Getting Started

## Requirements

* [Python 3.10+](#python)
* [uv](#uv)
* [Google Cloud SDK](#google-cloud-sdk)
* [Docker](#docker) (optional, for building images)

### Python

Python 3.10 or higher is required (3.10 through 3.13 are tested in CI). If you use `uv`, it will automatically manage Python versions for you.

### UV

https://docs.astral.sh/uv/

If you are on macOS, it is recommended to install via homebrew for automatic updates:

```bash
brew install uv
```

!!! tip

    uv is a fast Python package manager that handles dependency resolution, virtual environments,
    and Python version management. It's the recommended way to work with gc-batch.


### Google Cloud SDK

https://cloud.google.com/sdk/docs/install

The Google Cloud SDK is required for authentication and API access. After installation:

```bash
# Authenticate with your Google account
gcloud auth login

# Set your default project
gcloud config set project YOUR_PROJECT_ID

# Enable the Batch API
gcloud services enable batch.googleapis.com
```

### Docker

https://docs.docker.com/get-started/get-docker/

Docker is optional but needed if you want to build and push container images for your batch jobs.


## Installation

### From Source

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd gc-batch
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Install globally** (optional):
   ```bash
   uv tool install --force --no-cache ./
   ```

   This makes `gc-batch` available system-wide.


### All of Us Researcher Workbench Setup

On the All of Us Researcher Workbench, install `gc-batch` as described above, then
pass `--job-profile all-of-us` when creating jobs. See
[the built-in profile](../guides/configuration.md#the-built-in-all-of-us-profile).


## Development Setup

For contributing to gc-batch, install with development dependencies:

```bash
uv sync --group dev
```

### Running Tests

```bash
uv run pytest
```

### Code Formatting

```bash
uv run ruff format
uv run ruff check --fix
```


## Verifying Installation

After installation, verify everything is working:

```bash
# Check the CLI is installed
gc-batch --help

# List jobs (requires GCP authentication)
gc-batch list-jobs --since 1h
```
