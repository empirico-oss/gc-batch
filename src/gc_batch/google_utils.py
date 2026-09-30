"""Google Cloud utility functions for gc-batch.

This module provides utility functions for working with Google Cloud resources,
including parsing job resource names.

Classes:
    GoogleUtils: Static utility methods for Google Cloud operations.
"""

from google.cloud.batch_v1.types import Job as GCSBatchJob


class GoogleUtils:
    """Utility methods for working with Google Cloud Batch jobs.

    Provides static methods for parsing job resource names.

    Example:
        ```python
        from gc_batch.google_utils import GoogleUtils

        job = client.get_job("my-job")

        # Get just the job name (without the full resource path)
        job_name = GoogleUtils.get_job_name(job)
        # Returns: "my-job-1234567890"

        # Get the project ID from the job
        project_id = GoogleUtils.get_project_id(job)
        # Returns: "my-project-id"
        ```
    """

    @staticmethod
    def get_project_id(job: GCSBatchJob) -> str:
        """Extract the project ID from a job's resource name.

        Args:
            job: The GCSBatchJob object.

        Returns:
            The project ID extracted from the job's full resource path.

        Example:
            For a job with name "projects/my-project/locations/us-central1/jobs/job01",
            returns "my-project".
        """
        # this will be like: projects/123456/locations/us-central1/jobs/job01
        # so we want to return the 123456
        return job.name.split("/")[1]

    @staticmethod
    def get_job_name(job: GCSBatchJob) -> str:
        """Extract the job name from a job's resource name.

        Args:
            job: The GCSBatchJob object.

        Returns:
            The job name (last segment of the resource path).

        Example:
            For a job with name "projects/my-project/locations/us-central1/jobs/my-job",
            returns "my-job".
        """
        return job.name.split("/")[-1]
