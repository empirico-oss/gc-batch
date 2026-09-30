"""Job request and configuration models for Google Cloud Batch.

This module contains Pydantic models for configuring and creating Batch jobs,
including machine type helpers, job configuration, and job requests.
"""

import re

from pydantic import BaseModel, Field, field_validator

from gc_batch.constants import BatchProvisioningModel, Constants, CustomStrEnum
from gc_batch.settings import JobProfile
from gc_batch.utils import get_current_account


class BatchBootDiskType(CustomStrEnum):
    """Supported boot disk type strings for Batch jobs.

    This is the union of disk types supported on at least one machine generation;
    use :meth:`MachineTypeHelper.disk_type_supported` to check compatibility with
    a specific machine type.
    """

    HYPERDISK_BALANCED = "hyperdisk-balanced"
    HYPERDISK_BALANCED_HIGH_AVAILABILITY = "hyperdisk-balanced-high-availability"
    HYPERDISK_EXTREME = "hyperdisk-extreme"
    PD_STANDARD = "pd-standard"
    PD_BALANCED = "pd-balanced"
    PD_SSD = "pd-ssd"


class MachineTypeHelper:
    """Helper class for working with GCP machine types.

    Provides utilities for determining compatible disk types, checking machine type
    generations, and identifying LSSD (Local SSD) machine types.

    Example:
        ```python
        from gc_batch import MachineTypeHelper

        # Check if a machine type is LSSD
        is_lssd = MachineTypeHelper.is_lssd_machine_type("c4-standard-8-lssd")
        # Returns: True

        # Get supported disk types for a machine type
        disk_types = MachineTypeHelper.supported_disk_types("n2-standard-4")
        # Returns: ["hyperdisk-balanced", "hyperdisk-balanced-high-availability", ...]

        # Get the default disk type
        default = MachineTypeHelper.get_default_disk_type("e2-standard-2")
        # Returns: "pd-standard"
        ```
    """

    @staticmethod
    def supported_disk_types(type_name: str) -> list[str]:
        """Get the list of supported disk types for a machine type.

        Args:
            type_name: The GCP machine type name (e.g., "n2-standard-4").

        Returns:
            List of supported disk type strings for this machine type.

        Note:
            - Generation 4+ machines (c4, m4, etc.) only support hyperdisk types.
            - Generation 3 machines support both hyperdisk and pd-* types.
            - Older generations only support pd-* types.
        """
        if MachineTypeHelper.is_new_generation_machine_type(type_name):
            return [
                "hyperdisk-balanced",
                "hyperdisk-balanced-high-availability",
                "hyperdisk-extreme",
            ]
        elif MachineTypeHelper.is_mid_generation_machine_type(type_name):
            return [
                "hyperdisk-balanced",
                "hyperdisk-balanced-high-availability",
                "hyperdisk-extreme",
                "pd-standard",
                "pd-balanced",
                "pd-ssd",
            ]
        else:
            return [
                "pd-standard",
                "pd-balanced",
                "pd-ssd",
            ]

    @staticmethod
    def disk_type_supported(disk_type: str, type_name: str) -> bool:
        """Check if a disk type is supported for a given machine type.

        Args:
            disk_type: The disk type to check (e.g., "pd-balanced").
            type_name: The machine type name (e.g., "n2-standard-4").

        Returns:
            True if the disk type is supported, False otherwise.
        """
        return disk_type in MachineTypeHelper.supported_disk_types(type_name)

    @staticmethod
    def is_lssd_machine_type(type_name: str) -> bool:
        """Check if a machine type has pre-attached Local SSDs.

        LSSD machine types (e.g., "c4-standard-8-lssd") come with Local SSDs
        automatically attached and cannot have additional SSDs manually attached.

        Args:
            type_name: The machine type name to check.

        Returns:
            True if the machine type is an LSSD type, False otherwise.
        """
        return "lssd" in type_name.lower()

    @staticmethod
    def get_default_disk_type(type_name: str) -> str:
        """Get the default disk type for a machine type.

        Args:
            type_name: The machine type name (e.g., "n2-standard-4").

        Returns:
            The default (first) supported disk type for this machine type.
        """
        return MachineTypeHelper.supported_disk_types(type_name)[0]

    @staticmethod
    def is_new_generation_machine_type(type_name: str) -> bool:
        """Check if a machine type is generation 4 or newer.

        Args:
            type_name: The machine type name (e.g., "c4-standard-8").

        Returns:
            True if generation 4+, False otherwise.
        """
        return MachineTypeHelper._generation_check(type_name, 4)

    @staticmethod
    def is_mid_generation_machine_type(type_name: str) -> bool:
        """Check if a machine type is generation 3 or newer.

        Args:
            type_name: The machine type name (e.g., "n3-standard-4").

        Returns:
            True if generation 3+, False otherwise.
        """
        return MachineTypeHelper._generation_check(type_name, 3)

    @staticmethod
    def _generation_check(type_name: str, generation: int) -> bool:
        """Check if a machine type is at least the specified generation.

        Args:
            type_name: The machine type name.
            generation: The minimum generation to check for.

        Returns:
            True if the machine type is at least the specified generation.

        Raises:
            ValueError: If the machine type name cannot be parsed.
        """
        val = type_name.lower()
        m = re.match(r"^([a-z]+)(\d)", val)
        if m:
            return int(m.groups()[1]) >= generation

        raise ValueError(f"Invalid machine type: {type_name}, could not parse generation")


class BatchJobConfig(BaseModel):
    """Configuration for a Google Cloud Batch job.

    This model contains all the configuration options for creating a Batch job,
    including machine specifications, storage, networking, and environment settings.

    Attributes:
        default_task_count: Number of tasks in the job (default: 1).
        default_parallelism: Maximum tasks to run in parallel (default: 1).
        machine_type: GCP machine type (e.g., "e2-standard-2", "n2-standard-4").
        boot_disk_size: Boot disk size in GB (default: 30).
        boot_disk_type: Boot disk type (:class:`BatchBootDiskType`).
        input_bucket: GCS bucket path for input data (without gs:// prefix).
        input_dir: Mount point for input data in container (default: "/mnt/input").
        input_billing_project: Billing project for requester-pays input buckets.
        output_bucket: GCS bucket path for output data (without gs:// prefix).
        output_dir: Mount point for output data in container (default: "/mnt/output").
        logs_bucket: GCS bucket path (without gs:// prefix) to write job logs to.
            When set, logs go to this bucket path instead of Cloud Logging. Include a
            subfolder in the path to separate logs per job.
        logs_billing_project: Billing project for requester-pays logs buckets.
        local_ssd_size_gb: Size of local SSD in GB (must be multiple of 375).
        local_ssd_device_name: Device name for local SSD (default: "local-ssd-0").
        local_ssd_mount_path: Mount path for local SSD (default: "/mnt/local_ssd").
        provisioning_model: VM provisioning model (STANDARD, SPOT, or PREEMPTIBLE).
        network: VPC network path for the VM.
        subnetwork: Subnetwork path for the VM.
        service_account: Service account email to use for the job.
        use_private_address: Whether to use private IP (no external IP).
        regions: List of allowed regions for job placement.
        zones: List of allowed zones for job placement.
        user_env_dict: Custom environment variables for the container.

    Example:
        ```python
        from gc_batch import BatchJobConfig

        # Basic configuration
        config = BatchJobConfig(
            machine_type="n2-standard-4",
            boot_disk_type="pd-balanced",
            boot_disk_size=50,
        )

        # Configuration with GCS mounts
        config = BatchJobConfig(
            machine_type="n2-standard-8",
            boot_disk_type="pd-ssd",
            input_bucket="my-bucket/input-data",
            output_bucket="my-bucket/output-data",
        )

        # Configuration with local SSD
        config = BatchJobConfig(
            machine_type="n2-standard-4",
            boot_disk_type="pd-balanced",
            local_ssd_size_gb=375,
            local_ssd_mount_path="/mnt/fast",
        )
        ```
    """

    default_task_count: int = Field(default=1)
    default_parallelism: int = Field(default=1)
    output_location: str | None = Field(default=None)
    cores: int = Field(default=1)
    ram_gb: int = Field(default=4)
    machine_type: str
    boot_disk_size: int = Field(default=30)
    boot_disk_type: BatchBootDiskType
    user_env_dict: dict[str, str] | None = Field(default=None)

    # Input and output bucket configuration
    input_bucket: str | None = Field(default=None)
    input_dir: str | None = Field(default=Constants.INPUT_DIR)
    input_billing_project: str | None = Field(
        default=None, description="Billing project for input bucket access"
    )
    output_bucket: str | None = Field(default=None)
    output_dir: str | None = Field(default=Constants.OUTPUT_DIR)

    # Log output configuration
    logs_bucket: str | None = Field(
        default=None,
        description=(
            "GCS bucket path (without the gs:// prefix) where job logs will be "
            "written, e.g. 'my-bucket/batch-logs'. When set, logs are written to "
            "this bucket path instead of Cloud Logging; include a subfolder to "
            "separate logs per job. Useful when Cloud Logging is not accessible. "
            "Note: Batch supports a single log destination, so enabling this "
            "disables Cloud Logging for the job."
        ),
    )
    logs_billing_project: str | None = Field(
        default=None,
        description="Billing project for requester-pays logs bucket access",
    )

    # Networking options
    network: str | None = Field(
        default=None, description="Network to use (e.g., 'global/networks/network')"
    )
    subnetwork: str | None = Field(
        default=None,
        description="Subnetwork to use (e.g., 'regions/us-central1/subnetworks/subnetwork')",
    )
    service_account: str | None = Field(default=None, description="Service account email to use")
    use_private_address: bool = Field(
        default=False, description="Use private IP address (no external IP)"
    )
    regions: list[str] | None = Field(default=None, description="List of regions to use")
    zones: list[str] | None = Field(default=None, description="List of zones to use")

    # Local SSD configuration

    local_ssd_size_gb: int | None = Field(
        default=None,
        description="Size of local SSD in GB (must be multiple of 375 GB). If specified, a local SSD will be attached.",
    )
    local_ssd_device_name: str | None = Field(
        default="local-ssd-0",
        description="Device name for the local SSD (default: 'local-ssd-0')",
    )
    local_ssd_mount_path: str | None = Field(
        default=None,
        description="Mount path for the local SSD in the container (default: '/mnt/local_ssd')",
    )
    provisioning_model: BatchProvisioningModel | None = Field(
        default=None,
        description="Provisioning model: 'STANDARD', 'SPOT', or 'PREEMPTIBLE'. SPOT is recommended for cost savings. Accepts string input which is converted to enum.",
    )

    @field_validator("provisioning_model", mode="before")
    @classmethod
    def validate_provisioning_model(cls, v) -> BatchProvisioningModel | None:
        """Convert string input to BatchProvisioningModel enum before validation."""
        if v is None:
            return None
        if isinstance(v, str):
            return BatchProvisioningModel(v.upper())
        return v

    @field_validator("boot_disk_type", mode="before")
    @classmethod
    def validate_boot_disk_type(cls, v) -> BatchBootDiskType | None:
        """Convert string input to BatchBootDiskType enum before validation."""
        if isinstance(v, str):
            return BatchBootDiskType(v)
        return v

    def apply_profile(self, profile: JobProfile) -> "BatchJobConfig":
        """Apply a job profile's networking and VM settings to this config.

        This is what ``gc-batch create --job-profile`` does, exposed for library
        callers. Fields the profile leaves unset are left untouched, so a profile
        can be applied over a config that already has other settings.

        Args:
            profile: The :class:`~gc_batch.settings.JobProfile` to apply, usually
                taken from ``settings.job_profiles[name]``.

        Returns:
            This config, mutated in place, to allow chaining after construction.

        Raises:
            ValueError: If the profile sets ``service_account_from_gcloud`` but no
                authenticated ``gcloud`` account could be resolved.

        Example:
            ```python
            from gc_batch import BatchJobConfig, GCBatchSettings

            settings = GCBatchSettings.load()
            config = BatchJobConfig(
                machine_type="n2-standard-4",
                boot_disk_type="pd-balanced",
            ).apply_profile(settings.job_profiles["all-of-us"])
            ```
        """
        if profile.network is not None:
            self.network = profile.network
        if profile.subnetwork is not None:
            self.subnetwork = profile.subnetwork
        if profile.regions is not None:
            self.regions = profile.regions
        self.use_private_address = profile.use_private_address

        if profile.service_account_from_gcloud:
            current_account = get_current_account()
            if not current_account:
                raise ValueError(
                    "This job profile resolves the service account from gcloud, but no "
                    "authenticated account was found. Please run `gcloud auth login`."
                )
            self.service_account = current_account

        return self


class JobRequest(BaseModel):
    """Request to create a new Google Cloud Batch job.

    This model represents a complete job creation request, combining the job
    metadata with the job configuration.

    Attributes:
        job_name: Name for the job (will be timestamped, and prefixed if
            ``settings.job_name_prefix`` is configured).
        docker_image: Docker image URI to use for the job container.
        command: Command to run inside the container.
        args: Additional arguments to pass to the command (optional).
        config: BatchJobConfig with machine and storage settings.
        labels: Custom labels to attach to the job for filtering and organization.

    Example:
        ```python
        from gc_batch import JobRequest, BatchJobConfig

        config = BatchJobConfig(
            machine_type="n2-standard-4",
            boot_disk_type="pd-balanced",
            input_bucket="my-bucket/data",
            output_bucket="my-bucket/results",
        )

        request = JobRequest(
            job_name="data-analysis",
            docker_image="gcr.io/my-project/analyzer:latest",
            command="python /app/analyze.py",
            args="--input /mnt/input --output /mnt/output",
            config=config,
            labels={"team": "data-science", "environment": "production"},
        )
        ```
    """

    job_name: str = Field(default="default")
    docker_image: str = Field(default="ubuntu:latest")
    command: str = Field(default="echo 'Hello, World!'")
    args: str = Field(default="")
    config: BatchJobConfig
    labels: dict[str, str] | None = Field(
        default=None, description="Custom labels for the Batch job"
    )
