"""Constants and enums for gc-batch.

This module contains constant values, enums, and configuration classes used
throughout the gc-batch package.

Classes:
    BatchProvisioningModel: VM provisioning model options (STANDARD, SPOT, PREEMPTIBLE).
    Constants: File paths and mount point constants.
    EnvironmentVariables: Standard environment variables set in job containers.
"""

import os
from enum import Enum

from google.cloud.batch_v1.types import AllocationPolicy, Environment


class CustomStrEnum(str, Enum):
    """Custom StrEnum implementation for Python 3.10 compatibility.

    Mimics the behavior of Python 3.11+ StrEnum class.
    Members must be strings and can be compared directly with strings.
    """

    def __str__(self) -> str:
        """Return the string value of the enum member."""
        return self.value

    def __repr__(self) -> str:
        """Return a representation that shows the enum name and value."""
        return f"<{self.__class__.__name__}.{self.name}: {self.value!r}>"


class BatchProvisioningModel(CustomStrEnum):
    """VM provisioning model for Google Cloud Batch jobs.

    Controls how VMs are allocated for batch jobs, affecting both cost and availability.

    Attributes:
        STANDARD: Standard VMs with guaranteed availability (most expensive).
        SPOT: Preemptible VMs at reduced cost, may be terminated if capacity is needed.
        PREEMPTIBLE: Legacy preemptible model (deprecated, use SPOT instead).

    Example:
        ```python
        from gc_batch.constants import BatchProvisioningModel

        # Use SPOT for cost savings on fault-tolerant workloads
        model = BatchProvisioningModel.SPOT

        # Convert to Google Cloud Batch API enum
        api_model = model.to_batch_provisioning_model()
        ```

    Note:
        SPOT VMs are typically 60-91% cheaper than STANDARD VMs but can be
        preempted at any time. Use SPOT for fault-tolerant batch workloads.
    """

    STANDARD = "STANDARD"
    SPOT = "SPOT"
    PREEMPTIBLE = "PREEMPTIBLE"

    def to_batch_provisioning_model(self) -> AllocationPolicy.ProvisioningModel:
        """Convert to Google Cloud Batch API ProvisioningModel enum.

        Returns:
            The corresponding AllocationPolicy.ProvisioningModel value.

        Raises:
            ValueError: If the provisioning model value is invalid.
        """
        if self.value == "STANDARD":
            model = AllocationPolicy.ProvisioningModel.STANDARD
        elif self.value == "SPOT":
            model = AllocationPolicy.ProvisioningModel.SPOT
        elif self.value == "PREEMPTIBLE":
            model = AllocationPolicy.ProvisioningModel.PREEMPTIBLE
        else:
            raise ValueError(f"Invalid provisioning model: {self.value}")
        return AllocationPolicy.ProvisioningModel(model)


class Constants(CustomStrEnum):
    """File path and mount point constants used by gc-batch.

    These constants define the standard paths used for mounting disks and
    storing logs in batch job containers.

    Attributes:
        DATA_DISK_NAME: Name of the data disk device.
        VOLUME_MOUNT_POINT: Physical disk mount point on the VM.
        INPUT_MOUNT_POINT: Physical mount point for input data on the VM.
        OUTPUT_MOUNT_POINT: Physical mount point for output data on the VM.
        LOGS_MOUNT_POINT: Physical mount point for the logs bucket on the VM.
        OUTPUT_DIR: Default output directory inside the Docker container.
        INPUT_DIR: Default input directory inside the Docker container.
        DATA_MOUNT_POINT: Data directory inside the Docker container.
        BATCH_LOG_DIR: Where Google Cloud Batch API writes logs.
        LOGGING_DIR: Where the Docker container reads/filters logs.
        LOG_VOLUME_CONFIG: Volume configuration string for Docker.
        CLOUD_SDK_IMAGE: Default Google Cloud SDK Docker image.
    """

    DATA_DISK_NAME = "datadisk"
    VOLUME_MOUNT_POINT = "/mnt/disks/data"  # Physical disk mount point on the VM
    INPUT_MOUNT_POINT = "/mnt/disks/input"  # Physical mount point on the VM
    OUTPUT_MOUNT_POINT = "/mnt/disks/output"  # Physical mount point on the VM
    LOGS_MOUNT_POINT = "/mnt/disks/logs"  # Physical mount point for the logs bucket on the VM
    OUTPUT_DIR = "/mnt/output"  # Docker container mount point
    INPUT_DIR = "/mnt/input"  # Docker container mount point
    DATA_MOUNT_POINT = "/mnt/data"  # Docker container mount point
    BATCH_LOG_DIR = "/mnt/disks/data/.logging"  # Where Batch API writes logs
    LOGGING_DIR = "/mnt/data/.logging"  # Where Docker container reads/filters logs
    LOG_VOLUME_CONFIG = "/mnt/disks/data:/mnt/data"  # Volume configuration for Docker container
    CLOUD_SDK_IMAGE = "gcr.io/google.com/cloudsdktool/cloud-sdk:294.0.0-slim"  # Cloud SDK image


class EnvironmentVariables(CustomStrEnum):
    """Environment variables automatically set in batch job containers.

    These environment variables are set by gc-batch to provide standard paths
    for input and output data in job containers.

    Attributes:
        INPUT_DIR: Environment variable name for the input directory path.
        OUTPUT_DIR: Environment variable name for the output directory path.

    Example:
        In your container code, access these variables:

        ```python
        import os

        input_dir = os.environ.get('INPUT_DIR', '/mnt/input')
        output_dir = os.environ.get('OUTPUT_DIR', '/mnt/output')
        ```
    """

    INPUT_DIR = "INPUT_DIR"
    OUTPUT_DIR = "OUTPUT_DIR"

    @staticmethod
    def create_env(
        input_dir: str,
        output_dir: str,
        user_env_dict: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Create an Environment object with standard and custom variables.

        Args:
            input_dir: Path to the input directory in the container.
            output_dir: Path to the output directory in the container.
            user_env_dict: Optional dictionary of additional environment variables.

        Returns:
            An Environment object with all variables set.
        """
        environment = Environment()
        environment.variables = {
            EnvironmentVariables.INPUT_DIR.value: input_dir,
            EnvironmentVariables.OUTPUT_DIR.value: output_dir,
        }
        if user_env_dict:
            environment.variables.update(user_env_dict)
        return environment

    @staticmethod
    def create_env_dict_from_string(env_string: str) -> dict[str, str]:
        """Parse environment variables from a comma-separated string.

        Args:
            env_string: Environment variables as "key1=value1,key2=value2".

        Returns:
            Dictionary of environment variable key-value pairs.
        """
        env_dict = {}
        for env in env_string.split(","):
            key, value = env.split("=")
            env_dict[key] = value
        return env_dict

    def get_env_value(self) -> str | None:
        """Get the current value of this environment variable.

        Returns:
            The environment variable's value, or None if it is not set.
        """
        return os.getenv(self.value, None)
