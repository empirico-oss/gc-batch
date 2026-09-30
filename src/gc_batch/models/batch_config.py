"""Configuration models for the gc-batch client.

This module contains configuration classes used to initialize the GCBatchClient.
"""

from pydantic import BaseModel, Field

from gc_batch.settings import GCBatchSettings


class BatchClientConfig(BaseModel):
    """Configuration for the GCBatchClient.

    This configuration is used to initialize a GCBatchClient instance with
    the necessary GCP project and location settings.

    Attributes:
        location: The GCP region where Batch jobs will be created (e.g., "us-central1").
        project_id: The GCP project ID where Batch jobs will be managed.
        settings: Deployment-specific configuration (job-name prefix, job
            profiles, etc.). Defaults to :class:`GCBatchSettings` with neutral
            values.

    Example:
        ```python
        from gc_batch import BatchClientConfig, GCBatchClient

        config = BatchClientConfig(
            location="us-central1",
            project_id="my-gcp-project"
        )
        client = GCBatchClient(config)
        ```
    """

    location: str
    project_id: str
    settings: GCBatchSettings = Field(default_factory=GCBatchSettings)
