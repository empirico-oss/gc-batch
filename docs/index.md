# gc-batch

A command-line interface and Python client for managing Google Cloud Batch jobs with support for job creation, monitoring, logging, and filtering by labels.

## Features

- 🚀 **Create Batch Jobs**: Easy job creation with Docker images and custom commands
- 📋 **List & Filter Jobs**: List jobs with powerful filtering by labels and other criteria
- 📝 **View Job Logs**: Access stdout, stderr, and application logs from GCS
- 🏷️ **Label Management**: Organize jobs with custom labels for team, environment, project, etc.
- 🎯 **User-Specific Jobs**: Filter jobs by the current user who created them
- 🐍 **Python Library**: Submit and monitor jobs from your own code, not just the CLI

## Quick Start

### Create Your First Job

```bash
gc-batch create \
  --job-name my-first-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py"
```

### List Your Jobs

```bash
# List all jobs
gc-batch list-jobs

# List jobs created by you
gc-batch list-my-jobs
```

### Monitor Job Status

```bash
gc-batch status --job-name my-first-job-1234567890
```

### Or Use It From Python

```python
from gc_batch import BatchClientConfig, BatchJobConfig, GCBatchClient, JobRequest

client = GCBatchClient(BatchClientConfig(project_id="my-project", location="us-central1"))

job = client.create_job(
    JobRequest(
        job_name="my-first-job",
        docker_image="gcr.io/my-project/my-image:latest",
        command="python /app/main.py",
        config=BatchJobConfig(
            machine_type="e2-standard-2",
            boot_disk_type="pd-balanced",
        ),
    )
)
print(job.name)
```

See the **[Python API guide](guides/python-api.md)** for the full library surface.

## Documentation

- **[Getting Started](development/index.md)**: Installation and setup
- **[Commands Reference](guides/commands.md)**: Complete CLI command documentation
- **[Python API](guides/python-api.md)**: Using gc-batch as a library
- **[Development Guide](development/developing.md)**: Contributing to gc-batch

### Guides

- **[Quick Start Guide](guides/quick-start.md)**: Getting up and running quickly
- **[Input/Output Mounts](guides/mounts.md)**: Working with GCS bucket mounts
- **[Local SSD Storage](guides/local-ssd.md)**: High-performance local storage options
- **[Label Management](guides/labels.md)**: Organize and filter jobs with labels
- **[Configuration](guides/configuration.md)**: Default settings and customization
- **[Example Workflows](guides/examples.md)**: Real-world usage examples
- **[Troubleshooting](guides/troubleshooting.md)**: Common issues and solutions

## Project Layout

```
gc-batch/
├── src/
│   └── gc_batch/         # Main CLI package
│       ├── client.py     # Batch client implementation
│       ├── models/       # Pydantic models
│       └── entrypoint.py # CLI entry point
├── tests/                # Test suite
├── docs/                 # Documentation
└── pyproject.toml        # Project configuration
```

## Getting Help

```bash
# General help
gc-batch --help

# Command-specific help
gc-batch create --help
gc-batch list-jobs --help
gc-batch status --help
gc-batch logs --help
```
