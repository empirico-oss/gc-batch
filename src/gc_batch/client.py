"""Google Cloud Batch client for creating and managing Batch jobs.

This module provides the main client class for interacting with the Google Cloud
Batch API. It handles job creation, listing, status monitoring, and log retrieval.
"""

import logging
import time
from datetime import datetime

from google.cloud import batch_v1
from google.cloud.batch_v1.types import Job as GCSBatchJob
from google.cloud.batch_v1.types import Runnable, TaskGroup, TaskSpec

from gc_batch.batch_logging import BatchLogging
from gc_batch.constants import (
    Constants,
    EnvironmentVariables,
)
from gc_batch.gcs_logging import GCSLogReader
from gc_batch.logger import Logger, get_logger
from gc_batch.models.batch_config import BatchClientConfig
from gc_batch.models.job_request import BatchJobConfig, JobRequest, MachineTypeHelper
from gc_batch.utils import resolve_created_by_label


class GCBatchClient:
    """Client for managing Google Cloud Batch jobs.

    This is the main entry point for interacting with Google Cloud Batch. It provides
    methods for creating jobs, listing jobs with filters, checking job status,
    and retrieving job logs.

    Attributes:
        config: The BatchClientConfig with project and location settings.
        client: The underlying Google Cloud Batch API client.
        batch_logging: Helper for Cloud Logging operations.
        gcs_logging: Helper for reading logs written to a GCS bucket.

    Example:
        ```python
        from gc_batch import GCBatchClient, BatchClientConfig, JobRequest, BatchJobConfig

        # Initialize the client
        config = BatchClientConfig(project_id="my-project", location="us-central1")
        client = GCBatchClient(config)

        # Create a job
        job_config = BatchJobConfig(machine_type="e2-standard-2", boot_disk_type="pd-balanced")
        request = JobRequest(
            job_name="my-analysis",
            docker_image="python:3.12",
            command="python /app/main.py",
            config=job_config,
        )
        job = client.create_job(request)
        print(f"Created job: {job.name}")

        # List jobs by label
        jobs = client.list_jobs(labels={"team": "data-science"})

        # Get job status
        job = client.get_job("my-analysis-1234567890")
        print(f"Status: {job.status.state.name}")

        # Cancel a job
        client.cancel_job("projects/my-project/locations/us-central1/jobs/my-job")
        ```
    """

    def __init__(
        self,
        batch_client_config: BatchClientConfig,
        logger: Logger | None = None,
        log_level: int = logging.INFO,
    ):
        """Initialize the GCBatchClient.

        Args:
            batch_client_config: Configuration with project_id and location settings.
        """
        self.config = batch_client_config
        self.client = batch_v1.BatchServiceClient()
        self.logging = logger or get_logger(name="GCBatchClient", level=log_level)
        self.batch_logging = BatchLogging(
            config=batch_client_config,
            logger=self.logging,
        )
        # Reads logs for jobs created with --logs-bucket. Its GCS client is created
        # lazily, so constructing this never requires storage credentials.
        self.gcs_logging = GCSLogReader(
            config=batch_client_config,
            logger=self.logging,
        )

    def create_job(self, job_request: JobRequest) -> GCSBatchJob:
        """Create a new Google Cloud Batch job.

        Args:
            job_request: The JobRequest containing job configuration and settings.

        Returns:
            The created GCSBatchJob object with job details.

        Raises:
            Exception: If job creation fails.

        Example:
            ```python
            config = BatchJobConfig(machine_type="e2-standard-2", boot_disk_type="pd-balanced")
            request = JobRequest(
                job_name="my-job",
                docker_image="python:3.12",
                command="python main.py",
                config=config,
            )
            job = client.create_job(request)
            print(f"Job created: {job.name}")
            ```
        """
        try:
            new_job = self._create_job_spec(job_request)
            created_job = self.client.create_job(
                parent=self._get_parent_path(), job=new_job, job_id=new_job.name
            )
            return created_job
        except Exception as e:
            self.logging.error(f"Error creating job: {e}")
            raise e

    def get_job(self, job_name: str) -> GCSBatchJob:
        """Get a specific job by name.

        Args:
            job_name: The short job name (not the full resource path).

        Returns:
            The GCSBatchJob object with full job details.

        Example:
            ```python
            job = client.get_job("my-analysis-1234567890")
            print(f"Status: {job.status.state.name}")
            print(f"Created: {job.create_time}")
            ```
        """
        return self.client.get_job(
            name=f"projects/{self.config.project_id}/locations/{self.config.location}/jobs/{job_name}"
        )

    def cancel_job(self, job_name: str) -> None:
        """Cancel a running or queued job.

        Args:
            job_name: The full job resource path
                (e.g., "projects/my-project/locations/us-central1/jobs/my-job").

        Example:
            ```python
            job = client.get_job("my-job-name")
            client.cancel_job(job.name)  # Use the full name from the job object
            ```
        """
        self.client.cancel_job(name=job_name)

    def _list_jobs(
        self, filter_string: str | None = None, page_size: int = 100
    ) -> list[GCSBatchJob]:
        """
        List Batch jobs with optional filtering by labels or other criteria.

        Args:
            filter_string: Optional filter string to apply to the job list
            page_size: Number of jobs to return per page (max 1000)

        Returns:
            List of Batch jobs matching the filter criteria
        """
        try:
            request = batch_v1.ListJobsRequest(
                parent=self._get_parent_path(),
                page_size=page_size,
            )

            # Only add filter if it's provided and not empty
            if filter_string and filter_string.strip():
                request.filter = filter_string

            jobs = []
            page_result = self.client.list_jobs(request=request)

            for job in page_result:
                jobs.append(job)

            self.logging.debug(
                f"Found {len(jobs)} jobs matching filter: {filter_string or 'all jobs'}"
            )
            return jobs

        except Exception as e:
            self.logging.error(f"Error listing jobs: {e}")
            if "invalid list filter" in str(e):
                self.logging.error("Filter syntax error. Please check the filter string format.")
                self.logging.error('For labels, use: labels.key="value"')
                self.logging.error("For multiple conditions, use: condition1 AND condition2")
            raise

    def list_jobs(
        self,
        labels: dict[str, str] | None = None,
        name: str | None = None,
        since_time: datetime | None = None,
        status: str | None = None,
        page_size: int = 100,
    ) -> list[GCSBatchJob]:
        """
        List Batch jobs filtered by specific labels, name, since time, and status.

        Args:
            labels: Dictionary of label key-value pairs to filter by
            name: Filter by job name
            since_time: Filter by update time
            status: Filter by job status (RUNNING, SUCCEEDED, FAILED, QUEUED, etc.)
            page_size: Number of jobs to return per page (max 1000)

        Returns:
            List of Batch jobs with matching labels, name, since time, and status

        Examples:
            # List jobs with specific label
            jobs = client.list_jobs({"environment": "production"})

            # List jobs with multiple labels and name
            jobs = client.list_jobs({
                "team": "data-science",
                "project": "genomics",
            }, "genome-sequencing")

            # List jobs created in the last day
            jobs = client.list_jobs(since_time=datetime.now() - timedelta(days=1))

            # List only failed jobs
            jobs = client.list_jobs(status="FAILED")

            # List running jobs with specific label
            jobs = client.list_jobs({"team": "research"}, status="RUNNING")

            # List all jobs (no filters)
            jobs = client.list_jobs()
        """
        filters = []
        if since_time:
            filters.append(f'updateTime>="{since_time.strftime("%Y-%m-%dT%H:%M:%SZ")}"')
        if labels:
            for key, value in labels.items():
                # Use proper quoting for the filter string
                filters.append(f'labels.{key}="{value}"')
        if status:
            filters.append(f'status.state="{status}"')

        if len(filters) == 0:
            jobs = self._list_jobs(page_size=page_size)
        else:
            filter_string = " AND ".join(filters)
            jobs = self._list_jobs(filter_string, page_size)

        # The Batch API does not support name filtering via the filter parameter,
        # so filter client-side by matching the short job name.
        if name:
            jobs = [job for job in jobs if job.name.split("/")[-1] == name]

        return jobs

    def get_failure_message(self, job: GCSBatchJob) -> str:
        """
        Get concise failure information for a job.

        Args:
            job: The failed Google Cloud Batch job

        Returns:
            Concise failure message with essential error details
        """
        error_parts = [f"Job failed with state: {job.status.state.name}"]

        # Get the most relevant failure information from status events
        if hasattr(job.status, "status_events") and job.status.status_events:
            # Look for the most recent failure event
            failure_events = []
            for event in job.status.status_events:
                if (
                    hasattr(event, "description")
                    and event.description
                    and ("FAILED" in event.description or "failed" in event.description.lower())
                ):
                    failure_events.append(event.description)

            if failure_events:
                # Use the most detailed failure event (usually the last one)
                error_parts.append(f"Failure details: {failure_events[-1]}")
            else:
                # Fallback to the last event if no explicit failure found
                last_event = job.status.status_events[-1]
                if hasattr(last_event, "description") and last_event.description:
                    error_parts.append(f"Last status: {last_event.description}")

        # Check for task group failure counts
        if hasattr(job.status, "task_groups") and job.status.task_groups:
            for _group_name, task_group in job.status.task_groups.items():
                if hasattr(task_group, "counts") and task_group.counts:
                    counts = task_group.counts
                    if hasattr(counts, "FAILED") and counts.FAILED and int(counts.FAILED) > 0:
                        error_parts.append(f"Failed tasks: {counts.FAILED}")

        # Add job UID for reference (useful for debugging)
        if hasattr(job, "uid") and job.uid:
            error_parts.append(f"Job UID: {job.uid}")

        inference = self._infer_pre_container_failure(job)
        if inference:
            error_parts.append(inference)

        return "\n".join(error_parts)

    def _infer_pre_container_failure(self, job: GCSBatchJob) -> str | None:
        """Infer a pre-container failure from a total absence of task logs.

        When an image cannot be pulled, Batch fails the job without producing any
        task logs and without ever stating the reason: the only failure text is
        "… with exit code 1". The reason therefore cannot be retrieved, only
        inferred, and the result is labelled as an inference rather than presented
        as something Batch reported.

        Args:
            job: The failed job to diagnose.

        Returns:
            A labelled inference message, or ``None`` when the job is not failed,
            when log entries do exist, or when the logs could not be checked at
            all (in which case nothing can be concluded).
        """
        if job.status.state.name != "FAILED":
            return None

        try:
            if self._job_produced_log_entries(job):
                return None
        except Exception as e:
            # We cannot read the logs, so we cannot tell whether any were written.
            self.logging.debug(f"Could not check whether job {job.name} produced logs: {e}")
            return None

        image_uris = [
            runnable.container.image_uri
            for task_group in job.task_groups
            for runnable in task_group.task_spec.runnables
            if runnable.container.image_uri
        ]
        image_detail = (
            f" Image URI: {', '.join(image_uris)}." if image_uris else " No image URI was set."
        )
        return (
            "Inference (not reported by Batch): the container never started — the job "
            "produced no task logs at all. The Batch API does not report why, but this "
            "usually means the image could not be pulled (a bad tag, a missing image, or "
            f"no permission to pull it).{image_detail}"
        )

    def _job_produced_log_entries(self, job: GCSBatchJob) -> bool:
        """Report whether the job wrote any logs to its configured destination.

        Raises:
            Exception: If the log destination could not be queried at all.
        """
        if self.gcs_logging.uses_gcs_logs(job):
            return self.gcs_logging.has_log_objects(job)

        filter_str = self.batch_logging.get_filter_string_for_job(job)
        return bool(self.batch_logging._query_cloud_logs(filter_str, max_results=1))

    def get_cloud_logging_url(
        self,
        job: GCSBatchJob,
        severity: str = "DEFAULT",
        agent_logs: bool = False,
        custom_label_filters: dict[str, str] | None = None,
    ) -> str:
        """
        Get a URL to the Google Cloud Logging console filtered for this job.

        Args:
            job: The GCSBatchJob object to generate a URL for
            severity: Minimum severity level (e.g., "DEFAULT", "INFO", "WARNING", "ERROR")
            agent_logs: Whether to include agent logs (default: False)
            custom_label_filters: Optional mapping of label key to label value to
                filter the query by. If provided, overrides the job_uid filter.

        Returns:
            str: URL to the Cloud Logging console with filters applied
        """
        return self.batch_logging.get_cloud_logging_url(
            job, severity, agent_logs, custom_label_filters
        )

    def _create_job_spec(self, job_request: JobRequest) -> TaskGroup:
        """
        Create a task group for a job request

        Args:
            job_request (JobRequest): The job request to create a task group for

        Returns:
            TaskGroup: The task group for the job request
        """

        settings = self.config.settings
        job_name = f"{settings.job_name_prefix}{job_request.job_name}-{int(time.time())}"

        # Create labels for the job. "created-by" is set here rather than in the CLI
        # so that jobs submitted through the library are also found by `list-my-jobs`.
        labels = {
            "job-name": job_request.job_name,
            "created-using": settings.created_using_label,
            "created-by": resolve_created_by_label(settings.owner_email_env_vars),
            "created-at": str(int(time.time())),
        }

        # Add any custom labels from the job request; an explicit label wins over
        # the defaults above.
        if hasattr(job_request, "labels") and job_request.labels:
            labels.update(job_request.labels)

        volumes = []
        container_volumes_configs = []
        attached_disks = []

        if job_request.config.input_bucket:
            input_volume, volume_config = self.setup_gcs_volume(
                bucket_name=job_request.config.input_bucket,
                mount_path=job_request.config.input_dir or Constants.INPUT_DIR,
                disk_mount_path=Constants.INPUT_MOUNT_POINT,
                billing_project=job_request.config.input_billing_project,
            )
            volumes.append(input_volume)
            container_volumes_configs.append(volume_config)

        if job_request.config.output_bucket:
            output_volume, volume_config = self.setup_gcs_volume(
                bucket_name=job_request.config.output_bucket,
                mount_path=job_request.config.output_dir or Constants.OUTPUT_DIR,
                disk_mount_path=Constants.OUTPUT_MOUNT_POINT,
            )
            volumes.append(output_volume)
            container_volumes_configs.append(volume_config)

        # Optionally route Batch logs to a GCS bucket instead of Cloud Logging.
        # The logs bucket is mounted on the VM so the Batch agent can write logs to
        # it; it is intentionally not mounted into the user container.
        logs_path = None
        if job_request.config.logs_bucket:
            logs_volume, _ = self.setup_gcs_volume(
                bucket_name=f"{job_request.config.logs_bucket}/{job_name}",
                mount_path=Constants.LOGS_MOUNT_POINT,
                disk_mount_path=Constants.LOGS_MOUNT_POINT,
                billing_project=job_request.config.logs_billing_project,
                # The bucket subfolder may not exist yet; let gcsfuse handle it.
                implicit_dirs=True,
            )
            volumes.append(logs_volume)
            # Logs are written directly to the bucket path the user provided. To
            # separate logs per job, include a subfolder in the logs_bucket path.
            # The trailing slash is required by Batch to treat logs_path as the
            # root directory of the mounted bucket (see LogsPolicy.logs_path docs).
            logs_path = f"{Constants.LOGS_MOUNT_POINT}/"

        # Check if using an LSSD machine type (has local SSDs pre-attached)
        is_lssd_machine = MachineTypeHelper.is_lssd_machine_type(job_request.config.machine_type)
        needs_manual_ssd_mount = False

        if is_lssd_machine and job_request.config.local_ssd_size_gb:
            raise ValueError(
                "LSSD machine types do not support local SSD size configuration. Please use a non-LSSD machine type or remove the local SSD size configuration."
            )

        if is_lssd_machine:
            # For auto-attached LSSDs (like C4-lssd), we skip the explicit 'disks' config
            # but must flag that the disk needs manual formatting/mounting inside a runnable.
            self.logging.info(
                f"Using auto-attached LSSD machine type: {job_request.config.machine_type}. "
                "Local SSD will be manually formatted and mounted via a setup runnable."
            )
            needs_manual_ssd_mount = True

        if job_request.config.local_ssd_size_gb:
            # Manually attaching additional local SSD
            attached_ssd, volume, volume_config = self.setup_local_ssd(job_request.config)
            volumes.append(volume)
            container_volumes_configs.append(volume_config)
            attached_disks.append(attached_ssd)

        environment_variables = EnvironmentVariables.create_env(
            input_dir=job_request.config.input_dir or Constants.INPUT_DIR,
            output_dir=job_request.config.output_dir or Constants.OUTPUT_DIR,
            user_env_dict=job_request.config.user_env_dict,
        )

        vm_boot_disk = batch_v1.AllocationPolicy.Disk(
            type_=job_request.config.boot_disk_type,
            size_gb=job_request.config.boot_disk_size,
        )

        # Build InstancePolicy with optional provisioning_model
        instance_policy = batch_v1.AllocationPolicy.InstancePolicy(
            machine_type=job_request.config.machine_type,
            boot_disk=vm_boot_disk,
            disks=attached_disks,
        )
        if job_request.config.provisioning_model:
            instance_policy.provisioning_model = (
                job_request.config.provisioning_model.to_batch_provisioning_model()
            )

        allocation_policy = batch_v1.AllocationPolicy(
            instances=[
                batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
                    policy=instance_policy,
                )
            ],
            labels=labels,
        )

        # Add service account if specified
        if job_request.config.service_account:
            allocation_policy.service_account = batch_v1.ServiceAccount(
                email=job_request.config.service_account,
                scopes=[
                    "https://www.googleapis.com/auth/bigquery",
                    "https://www.googleapis.com/auth/compute",
                    "https://www.googleapis.com/auth/devstorage.full_control",
                    "https://www.googleapis.com/auth/genomics",
                    "https://www.googleapis.com/auth/logging.write",
                    "https://www.googleapis.com/auth/monitoring.write",
                ],
            )

        # Add network policy if network/subnetwork specified
        if (
            job_request.config.network
            or job_request.config.subnetwork
            or job_request.config.use_private_address
        ):
            if (
                not job_request.config.use_private_address
                or not job_request.config.network
                or not job_request.config.subnetwork
            ):
                raise ValueError(
                    "If Network/subnetwork/use_private_address are specified, all must be specified"
                )

            network_policy = batch_v1.AllocationPolicy.NetworkPolicy(
                network_interfaces=[
                    batch_v1.AllocationPolicy.NetworkInterface(
                        network=job_request.config.network,
                        subnetwork=job_request.config.subnetwork,
                        no_external_ip_address=job_request.config.use_private_address,
                    )
                ]
            )

            allocation_policy.network = network_policy

        # Add location policy if regions/zones specified
        if job_request.config.regions or job_request.config.zones:
            location_policy = batch_v1.AllocationPolicy.LocationPolicy()
            allowed_locations = []

            if job_request.config.regions:
                for region in job_request.config.regions:
                    allowed_locations.append(f"regions/{region}")

            if job_request.config.zones:
                for zone in job_request.config.zones:
                    allowed_locations.append(f"zones/{zone}")

            location_policy.allowed_locations = allowed_locations
            allocation_policy.location = location_policy

        job = GCSBatchJob(
            name=f"{job_name}",
            labels=labels,  # Add labels to the job
            task_groups=[
                TaskGroup(
                    task_count=job_request.config.default_task_count,
                    parallelism=job_request.config.default_parallelism,
                    task_spec=TaskSpec(
                        runnables=self._create_runnables(
                            job_request,
                            container_volumes_configs,
                            environment_variables,
                            needs_manual_ssd_mount,
                        ),
                        environment=environment_variables,
                        # Add volume mounting to access Batch API logs
                        # This mounts the physical disk to the container path
                        volumes=volumes,
                    ),
                )
            ],
            logs_policy=self.batch_logging.create_log_policy(logs_path=logs_path),
            allocation_policy=allocation_policy,
        )

        return job

    def _create_runnables(
        self,
        job_request: JobRequest,
        container_volumes_configs: list[str],
        environment_variables: dict[str, str],
        needs_manual_ssd_mount: bool,
    ) -> list[Runnable]:
        """Create the list of Runnable objects for a job.

        A job may have multiple runnables that execute in sequence:
        1. Optional: LSSD setup script (if using LSSD machine types)
        2. User container with the specified command

        Args:
            job_request: The job request with command and configuration.
            container_volumes_configs: Volume mount configurations for the container.
            environment_variables: Environment variables to set in the container.
            needs_manual_ssd_mount: Whether to add an LSSD setup runnable.

        Returns:
            List of Runnable objects to execute in the job.
        """
        runnables = []

        if needs_manual_ssd_mount:
            self.logging.info("Adding manual LSSD setup runnable.")
            # Add the runnable to format and mount the disk first
            runnables.append(
                self._create_manual_ssd_setup_runnable(
                    job_request.config.local_ssd_mount_path,
                )
            )
        # Add the container runnable
        runnables.append(
            self._create_user_runnable(
                job_request,
                container_volumes_configs,
                environment_variables,
            )
        )

        return runnables

    def _create_manual_ssd_setup_runnable(
        self,
        mount_point_path: str | None,
    ) -> Runnable:
        """
        Creates a Runnable to manually format and mount auto-attached Local SSDs.

        This script discovers Local SSDs using /dev/disk/by-id paths as recommended
        by Google Cloud documentation. It handles both NVMe and SCSI modes, and
        supports multiple SSDs by creating a RAID0 array if multiple devices are found.

        Reference: https://docs.cloud.google.com/compute/docs/disks/add-local-ssd#formatandmount
        """
        MOUNT_POINT = mount_point_path or "/mnt/local_ssd"

        # The script to format (ext4) and mount the disk(s).
        # Follows Google Cloud best practices for Local SSD discovery and mounting.
        ssd_setup_script = f"""#!/bin/bash
set -eu

echo "Starting manual LSSD setup"

# 1. Create the mount directory
sudo mkdir -p {MOUNT_POINT}

# 2. Discover Local SSD devices
# Check for NVMe mode devices first (google-local-nvme-ssd-*)
NVME_DEVICES=($(find /dev/disk/by-id -name "google-local-nvme-ssd-*" 2>/dev/null | sort))
# Check for SCSI mode devices (google-local-ssd-*)
SCSI_DEVICES=($(find /dev/disk/by-id -name "google-local-ssd-*" 2>/dev/null | sort))

# Combine both types
ALL_DEVICES=("${{NVME_DEVICES[@]}}" "${{SCSI_DEVICES[@]}}")

if [ ${{#ALL_DEVICES[@]}} -eq 0 ]; then
    echo "WARNING: No Local SSD devices found. Skipping format/mount."
    exit 0 # Allow the job to continue if no devices were attached
fi

echo "Found ${{#ALL_DEVICES[@]}} Local SSD device(s):"
for dev in "${{ALL_DEVICES[@]}}"; do
    echo "  - $dev"
done

# 3. Handle single vs multiple devices
if [ ${{#ALL_DEVICES[@]}} -eq 1 ]; then
    # Single device: format and mount directly
    DEVICE_PATH="${{ALL_DEVICES[0]}}"
    echo "Formatting single device $DEVICE_PATH with ext4..."
    sudo mkfs.ext4 -F -E lazy_itable_init=0,lazy_journal_init=0 "$DEVICE_PATH"
    
    echo "Mounting $DEVICE_PATH to {MOUNT_POINT}..."
    sudo mount -o discard,defaults "$DEVICE_PATH" {MOUNT_POINT}
else
    # Multiple devices: create RAID0 array
    echo "Multiple devices detected. Creating RAID0 array..."
    
    # Create RAID array
    sudo mdadm --create /dev/md0 --level=0 --raid-devices=${{#ALL_DEVICES[@]}} "${{ALL_DEVICES[@]}}"
    
    echo "Formatting RAID array /dev/md0 with ext4..."
    sudo mkfs.ext4 -F /dev/md0
    
    echo "Mounting /dev/md0 to {MOUNT_POINT}..."
    sudo mount -o discard,defaults /dev/md0 {MOUNT_POINT}
fi

# 4. Set permissions for the non-root user that the container will run as
echo "Setting permissions on {MOUNT_POINT}..."
sudo chmod a+w {MOUNT_POINT}

echo "LSSD setup complete. Mounted at {MOUNT_POINT}"
"""

        # We use a standard image that has bash and sudo utilities
        return Runnable(
            script=Runnable.Script(text=ssd_setup_script),
        )

    def _create_user_runnable(
        self,
        job_request: JobRequest,
        container_volumes_configs: list[str],
        environment_variables: dict[str, str],
    ) -> Runnable:
        """Create the user's container runnable.

        Builds a Runnable that runs the user's Docker container with the
        specified command, arguments, volumes, and environment variables.

        Args:
            job_request: The job request with docker image, command, and args.
            container_volumes_configs: Volume mount strings (e.g., "/host:/container").
            environment_variables: Environment variables for the container.

        Returns:
            A Runnable configured to run the user's container.

        Raises:
            ValueError: If no command is specified in the job request.
        """
        # Combine command and args
        full_command = job_request.command.strip()

        if not full_command:
            raise ValueError("Command is required")

        if job_request.args.strip():
            full_command = f"{full_command} {job_request.args.strip()}"

        is_lssd_machine = MachineTypeHelper.is_lssd_machine_type(job_request.config.machine_type)
        if is_lssd_machine:
            # This maps the host's manually mounted folder to the container's identical folder.
            # Note: This list is passed to the container spec, not the TaskSpec.
            container_volumes_configs.append("/mnt/local_ssd:/mnt/local_ssd")

        return Runnable(
            container=Runnable.Container(
                image_uri=job_request.docker_image,
                entrypoint="/bin/bash",
                commands=["-c", full_command],
                volumes=container_volumes_configs,
            ),
            environment=environment_variables,
        )

    def _get_parent_path(self) -> str:
        """Get the parent resource path for API calls.

        Returns:
            The parent path in format "projects/{project}/locations/{location}".
        """
        return f"projects/{self.config.project_id}/locations/{self.config.location}"

    def setup_volume(
        self, disk_type: str, disk_size: int, device_name: str, mount_path: str
    ) -> tuple[batch_v1.AllocationPolicy.AttachedDisk, batch_v1.AllocationPolicy.Disk]:
        """Create an attached disk and volume configuration.

        Args:
            disk_type: The disk type (e.g., "pd-balanced", "pd-ssd").
            disk_size: Disk size in GB.
            device_name: Device name for the disk.
            mount_path: Path where the disk will be mounted in the VM.

        Returns:
            Tuple of (AttachedDisk, Disk) configurations.
        """
        attached_disk = batch_v1.AllocationPolicy.AttachedDisk(
            new_disk=batch_v1.AllocationPolicy.Disk(
                type_=disk_type,
                size_gb=disk_size,
            ),
            device_name=device_name,  # This name must match the volume device_name above
        )
        volume = batch_v1.Volume(
            device_name=device_name,  # This should match your disk name
            mount_path=mount_path,
        )
        return attached_disk, volume

    def setup_gcs_volume(
        self,
        bucket_name: str,
        mount_path: str,
        disk_mount_path: str,
        read_only: bool = False,
        billing_project: str | None = None,
        implicit_dirs: bool = False,
    ) -> tuple[batch_v1.Volume, str]:
        """Configure a GCS bucket as a mounted volume.

        Creates a Volume configuration that mounts a Google Cloud Storage bucket
        path into the container, allowing the job to read/write files directly
        to GCS as if they were local files.

        Args:
            bucket_name: GCS bucket path (e.g., "my-bucket/data/input").
            mount_path: Mount path inside the container (e.g., "/mnt/input").
            disk_mount_path: Physical mount path on the VM.
            read_only: If True, pass gcsfuse's ``-o ro`` mount option. Defaults to
                False. NOTE: ``-o ro`` alone is known to break the mount, because
                it appears to override gcsfuse's default options rather than add
                to them; no caller currently sets this to True. Input mounts are
                writable, and callers should treat them as read-only by
                convention rather than relying on this flag.
            billing_project: Billing project for requester-pays buckets.
            implicit_dirs: If True, pass ``--implicit-dirs`` to gcsfuse so that
                objects under not-yet-existing prefixes (e.g. a per-job log
                subfolder) are usable without first creating placeholder objects.

        Returns:
            Tuple of (Volume, volume_config_string) where volume_config_string
            is the Docker volume mount format "host_path:container_path".

        Example:
            ```python
            volume, config = client.setup_gcs_volume(
                bucket_name="my-bucket/input-data",
                mount_path="/mnt/input",
                disk_mount_path="/mnt/disks/input",
                billing_project="my-billing-project",
            )
            ```
        """

        mount_opts = []
        if billing_project:
            mount_opts.append(f"--billing-project={billing_project}")
        if implicit_dirs:
            mount_opts.append("--implicit-dirs")
        if read_only:
            # TODO: Need to add additional options as just -o ro breaks the mount because it seems to override the default options
            mount_opts.append("-o ro")

        gcs_config = batch_v1.GCS(
            remote_path=f"{bucket_name}",
        )

        volume = batch_v1.Volume(
            gcs=gcs_config,
            mount_path=disk_mount_path,
            mount_options=mount_opts,
        )

        volume_config = f"{disk_mount_path}:{mount_path}"

        return volume, volume_config

    def setup_local_ssd(
        self, config: BatchJobConfig
    ) -> tuple[batch_v1.AllocationPolicy.AttachedDisk, batch_v1.Volume, str]:
        """Configure a local SSD for high-performance storage.

        Creates the configuration to attach a local SSD to the job VM for
        high-performance ephemeral storage. Local SSDs provide very high IOPS
        and low latency, ideal for temporary data processing.

        Args:
            config: BatchJobConfig with local_ssd_size_gb, local_ssd_device_name,
                and local_ssd_mount_path settings.

        Returns:
            Tuple of (AttachedDisk, Volume, volume_config_string).

        Raises:
            ValueError: If local_ssd_size_gb is None or not a multiple of 375 GB.

        Note:
            - Local SSD size must be a multiple of 375 GB.
            - Data on local SSDs is ephemeral and lost when the VM terminates.
            - Local SSDs are automatically formatted and mounted by Batch.

        Example:
            ```python
            config = BatchJobConfig(
                machine_type="n2-standard-4",
                boot_disk_type="pd-balanced",
                local_ssd_size_gb=375,
                local_ssd_mount_path="/mnt/fast",
            )
            attached_disk, volume, volume_config = client.setup_local_ssd(config)
            ```
        """
        if config.local_ssd_size_gb is None:
            raise ValueError(
                "Local SSD size is required - to use local SSD, you must specify the size in GB"
            )

        if config.local_ssd_size_gb % 375 != 0:
            raise ValueError(
                f"Local SSD size must be a multiple of 375 GB. "
                f"Specified size: {config.local_ssd_size_gb} GB"
            )

        attached_ssd = batch_v1.AllocationPolicy.AttachedDisk(
            new_disk=batch_v1.AllocationPolicy.Disk(
                type_="local-ssd",
                size_gb=config.local_ssd_size_gb,
            ),
            device_name=config.local_ssd_device_name,
        )

        # Create volume for local SSD
        vm_ssd_mount_path = f"/mnt/disks/{config.local_ssd_device_name}"
        container_ssd_mount_path = config.local_ssd_mount_path or "/mnt/local_ssd"

        volume = batch_v1.Volume(
            device_name=config.local_ssd_device_name,
            mount_path=vm_ssd_mount_path,
        )

        volume_config = f"{vm_ssd_mount_path}:{container_ssd_mount_path}"

        return attached_ssd, volume, volume_config
