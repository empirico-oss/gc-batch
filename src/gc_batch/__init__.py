"""gc-batch: Google Cloud Batch Job Management CLI and Python Client.

This package provides a command-line interface and Python library for managing
Google Cloud Batch jobs with support for job creation, monitoring, logging,
and filtering by labels.

Example:
    Using the CLI:

    ```bash
    gc-batch create --job-name my-job --docker-image python:3.12 --command "python main.py"
    gc-batch list_my_jobs
    gc-batch status --job-name my-job
    ```

    Using the Python client:

    ```python
    from gc_batch import GCBatchClient, BatchClientConfig, JobRequest, BatchJobConfig

    # Create a client
    config = BatchClientConfig(project_id="my-project", location="us-central1")
    client = GCBatchClient(config)

    # Create a job
    job_config = BatchJobConfig(machine_type="e2-standard-2", boot_disk_type="pd-balanced")
    request = JobRequest(
        job_name="my-job",
        docker_image="python:3.12",
        command="python main.py",
        config=job_config,
    )
    job = client.create_job(request)

    # List jobs
    jobs = client.list_jobs(labels={"team": "data-science"})
    ```

Modules:
    client: Main GCBatchClient class for interacting with Google Cloud Batch API.
    models: Pydantic models for job configuration and requests.
    batch_logging: Logging utilities for viewing job logs in Cloud Logging.
    gcs_logging: Reader for job logs written to a GCS bucket (--logs-bucket).
    utils: Utility functions for working with jobs.
"""

from gc_batch._version import version as __version__
from gc_batch.client import GCBatchClient
from gc_batch.models.batch_config import BatchClientConfig
from gc_batch.models.job_request import (
    BatchBootDiskType,
    BatchJobConfig,
    JobRequest,
    MachineTypeHelper,
)
from gc_batch.settings import GCBatchSettings, JobProfile

__all__ = [
    "__version__",
    "GCBatchClient",
    "BatchClientConfig",
    "BatchBootDiskType",
    "BatchJobConfig",
    "JobRequest",
    "MachineTypeHelper",
    "GCBatchSettings",
    "JobProfile",
]
