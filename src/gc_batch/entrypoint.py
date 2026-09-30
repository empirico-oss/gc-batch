"""Google Cloud Batch Job Management CLI

This CLI provides commands for managing Google Cloud Batch jobs including:
- Creating new jobs
- Listing and filtering jobs
- Monitoring job status
- Viewing job logs
- Deleting jobs
"""

import json
import os
import sys
from datetime import datetime, timedelta

import click
from google.api_core.exceptions import PermissionDenied
from google.protobuf.json_format import MessageToJson

from gc_batch.client import GCBatchClient
from gc_batch.constants import BatchProvisioningModel, Constants, EnvironmentVariables
from gc_batch.gcs_logging import GCSLogReader
from gc_batch.google_utils import GoogleUtils
from gc_batch.models.batch_config import BatchClientConfig
from gc_batch.models.job_request import (
    BatchBootDiskType,
    BatchJobConfig,
    JobRequest,
    MachineTypeHelper,
)
from gc_batch.settings import GCBatchSettings
from gc_batch.utils import get_gc_batch_version, resolve_created_by_label


def create_client(location: str, project_id: str, settings: GCBatchSettings) -> GCBatchClient:
    """Create a BatchClient instance."""
    return GCBatchClient(
        BatchClientConfig(
            location=location,
            project_id=project_id,
            settings=settings,
        )
    )


def parse_labels(labels_str: str) -> dict[str, str] | None:
    """Parse labels from a comma-separated string of key=value pairs."""
    if not labels_str:
        return None

    labels = {}
    for pair in labels_str.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            labels[key.strip()] = value.strip()

    return labels


def convert_labels_to_dict(labels) -> dict[str, str]:
    """Convert Google Cloud API labels object to a regular Python dictionary."""
    if not labels:
        return {}

    # Handle ScalarMapContainer (Google Cloud API object)
    if hasattr(labels, "items"):
        return dict(labels.items())

    # Handle regular dictionary
    if isinstance(labels, dict):
        return labels

    # Handle other cases
    return {}


def click_centered_header(message: str):
    """Click centered header with message centered in dashes"""
    # Calculate how many dashes to put on each side
    message_length = len(message)
    total_dashes = 80
    available_space = total_dashes - message_length

    if available_space <= 0:
        # Message is too long, just print it as is
        click.echo(message)
        return

    # Split available space between left and right sides
    left_dashes = available_space // 2
    right_dashes = available_space - left_dashes

    # Create the centered header
    header = "-" * left_dashes + message + "-" * right_dashes
    click.echo(header)


@click.group()
@click.version_option(version=get_gc_batch_version(), prog_name="gc-batch")
@click.option("--location", default="us-central1", help="GCP location")
@click.option("--project-id", default="", help="GCP project ID")
@click.option(
    "--config-file",
    default=None,
    help=(
        "Path to a gc-batch TOML settings file. When omitted, the standard "
        "discovery order is used: $GC_BATCH_CONFIG_FILE, ./gc-batch.toml, then "
        "$XDG_CONFIG_HOME/gc-batch/config.toml (or ~/.config/gc-batch/config.toml)."
    ),
)
@click.pass_context
def cli(ctx, location: str, project_id: str, config_file: str | None):
    """Google Cloud Batch Job Management CLI"""
    ctx.ensure_object(dict)
    settings = GCBatchSettings.load(config_file=config_file)

    resolved_project_id: str | None = project_id
    if not resolved_project_id:
        resolved_project_id = os.getenv("GOOGLE_PROJECT")

    if not resolved_project_id:
        resolved_project_id = settings.default_project_id

    ctx.obj["location"] = location
    ctx.obj["project_id"] = resolved_project_id
    ctx.obj["settings"] = settings


def _require_project_id(ctx) -> str:
    """Return the resolved GCP project id, or exit with an actionable error.

    Resolution happens in the group callback (``--project-id``, then
    ``$GOOGLE_PROJECT``, then the ``default_project_id`` setting). This is checked
    lazily so that ``--help`` and ``show-config`` remain usable when no project is
    configured yet.
    """
    project_id = ctx.obj.get("project_id")
    if not project_id:
        click.echo(
            "❌ No GCP project ID configured. Pass --project-id, set $GOOGLE_PROJECT, "
            "or set default_project_id in your gc-batch settings.",
            err=True,
        )
        sys.exit(1)
    return project_id


@cli.command()
@click.option("--job-name", required=True, help="Name for the job")
@click.option("--docker-image", required=True, help="Docker image to use")
@click.option("--command", required=True, help="Command to run")
@click.option(
    "--job-profile",
    default=None,
    help=(
        "Name of a configured job profile to apply (e.g. networking and service "
        "account settings). No profile is applied by default. Available profiles "
        "come from settings.job_profiles (built-in: 'all-of-us')."
    ),
)
@click.option("--args", default="", help="Command arguments")
@click.option("--labels", help="Labels as key=value,key2=value2")
@click.option("--task-count", type=int, default=1, help="Number of tasks")
@click.option("--parallelism", type=int, default=1, help="Parallelism level")
@click.option("--machine-type", default="e2-standard-2", help="Machine type")
@click.option("--boot-disk-size", type=int, default=30, help="Boot disk size in GB")
@click.option("--boot-disk-type", default="", help="Boot disk type")
@click.option("--input-bucket", default="", help="A gcs bucket folder to mount")
@click.option(
    "--input-billing-project",
    default="",
    help="Billing project for input bucket access",
)
@click.option("--output-bucket", default="", help="A gcs bucket folder to mount")
@click.option(
    "--input-dir",
    default=Constants.INPUT_DIR,
    help="A local mount point for the input bucket - default is /mnt/input - environment variable is INPUT_DIR",
)
@click.option(
    "--output-dir",
    default=Constants.OUTPUT_DIR,
    help="A local mount point for the output bucket - default is /mnt/output - environment variable is OUTPUT_DIR",
)
@click.option(
    "--logs-bucket",
    default="",
    help="A GCS bucket folder to write job logs to (e.g. my-bucket/batch-logs). When set, logs are written to this bucket path instead of Cloud Logging; include a subfolder to separate logs per job. Useful when Cloud Logging is not accessible.",
)
@click.option(
    "--logs-billing-project",
    default="",
    help="Billing project for the logs bucket (for requester-pays buckets)",
)
@click.option(
    "--env",
    default="",
    help="Environment variables as key=value,key2=value2",
)
@click.option(
    "--local-ssd-size-gb",
    type=int,
    default=None,
    help="Size of local SSD in GB (must be multiple of 375 GB). If specified, a local SSD will be attached.",
)
@click.option(
    "--local-ssd-mount-path",
    default=None,
    help="Mount path for the local SSD in the container (default: '/mnt/local_ssd')",
)
@click.option(
    "--local-ssd-device-name",
    default="local-ssd-0",
    help="Device name for the local SSD (default: 'local-ssd-0'), you probably don't need to specify this.",
)
@click.option(
    "--provisioning-model",
    type=click.Choice(["STANDARD", "SPOT", "PREEMPTIBLE"], case_sensitive=False),
    default=None,
    help="Provisioning model: STANDARD, SPOT, or PREEMPTIBLE. SPOT is recommended for cost savings (default: STANDARD)",
)
@click.pass_context
def create(
    ctx,
    job_name: str,
    docker_image: str,
    command: str,
    args: str,
    job_profile: str | None,
    labels: str,
    task_count: int,
    parallelism: int,
    machine_type: str,
    boot_disk_size: int,
    boot_disk_type: str,
    input_bucket: str,
    input_billing_project: str,
    output_bucket: str,
    input_dir: str,
    output_dir: str,
    logs_bucket: str,
    logs_billing_project: str,
    env: str,
    local_ssd_size_gb: int | None,
    local_ssd_mount_path: str | None,
    local_ssd_device_name: str,
    provisioning_model: str | None,
):
    """Create a new Batch job."""
    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])

    # Parse labels if provided. The "created-by" label is set by the client.
    labels_dict = parse_labels(labels) if labels else None

    if boot_disk_type == "":
        boot_disk_type = MachineTypeHelper.get_default_disk_type(type_name=machine_type)

    # remove the gcs bucket prefix; "" means the option was not supplied
    input_bucket_name: str | None = input_bucket.replace("gs://", "") if input_bucket else None
    output_bucket_name: str | None = output_bucket.replace("gs://", "") if output_bucket else None
    logs_bucket_name: str | None = logs_bucket.replace("gs://", "") if logs_bucket else None
    logs_unreadable = False  # profile says Cloud Logging is unreadable here

    user_env_dict = None
    if env != "":
        user_env_dict = EnvironmentVariables.create_env_dict_from_string(env)

    # Validate disk type compatibility with machine type
    if not MachineTypeHelper.disk_type_supported(disk_type=boot_disk_type, type_name=machine_type):
        click.echo(
            f"❌ You specified an invalid disk type for the machine type {machine_type}. Valid disk types are: {MachineTypeHelper.supported_disk_types(type_name=machine_type)}"
        )
        sys.exit(1)

    # Create job configuration
    job_config = BatchJobConfig(
        default_task_count=task_count,
        default_parallelism=parallelism,
        machine_type=machine_type,
        boot_disk_type=BatchBootDiskType(boot_disk_type),
        boot_disk_size=boot_disk_size,
        input_bucket=input_bucket_name,
        input_billing_project=input_billing_project if input_billing_project else None,
        input_dir=input_dir,
        output_bucket=output_bucket_name,
        output_dir=output_dir,
        logs_bucket=logs_bucket_name,
        logs_billing_project=logs_billing_project if logs_billing_project else None,
        user_env_dict=user_env_dict,
        local_ssd_size_gb=local_ssd_size_gb,
        local_ssd_device_name=local_ssd_device_name,
        local_ssd_mount_path=local_ssd_mount_path,
        provisioning_model=(
            BatchProvisioningModel(provisioning_model) if provisioning_model else None
        ),
    )

    if job_profile:
        settings = ctx.obj["settings"]
        profile = settings.job_profiles.get(job_profile)
        if profile is None:
            available = ", ".join(sorted(settings.job_profiles)) or "(none configured)"
            click.echo(
                f"❌ Unknown job profile '{job_profile}'. Available profiles: {available}",
                err=True,
            )
            sys.exit(1)

        click.echo(f"Applying job profile: {job_profile}")
        try:
            job_config.apply_profile(profile)
        except ValueError as error:
            click.echo(f"❌ {error}", err=True)
            sys.exit(1)

        logs_unreadable = profile.cloud_logging_unreadable and not logs_bucket
        if logs_unreadable:
            click.echo(
                f"⚠️  Job profile '{job_profile}' is for an environment where Cloud "
                "Logging usually cannot be read, and --logs-bucket was not set.",
                err=True,
            )
            click.echo(
                "   This job will write its logs to Cloud Logging, so "
                "`gc-batch logs print` will most likely fail with "
                '"403 Permission denied for all log views".',
                err=True,
            )
            click.echo(
                "   The log destination is fixed when the job is created and cannot "
                "be changed afterwards. To keep the logs readable, cancel and "
                "recreate with --logs-bucket BUCKET/PATH.",
                err=True,
            )

        if profile.service_account_from_gcloud:
            click.echo(f"Current account: {job_config.service_account}")

    # Create job request
    job_request = JobRequest(
        job_name=job_name,
        docker_image=docker_image,
        command=command,
        args=args,
        config=job_config,
        labels=labels_dict,
    )

    try:
        job = client.create_job(job_request)
        click.echo("✅ Job created successfully!")
        job_name = GoogleUtils.get_job_name(job)
        click.echo(f"   Name: {job_name}")
        click.echo(f"   UID: {job.uid}")
        if logs_bucket_name:
            click.echo(f"   Logs (GCS): gs://{logs_bucket_name}/")
        else:
            click.echo(f"   Cloud Logging URL: {client.get_cloud_logging_url(job)}")
            if logs_unreadable:
                click.echo(
                    "   ⚠️  That URL will most likely show nothing: this environment "
                    "cannot read Cloud Logging. Recreate with --logs-bucket to get "
                    "readable logs."
                )
        click.echo(f"   Full Name: {job.name}")
        click.echo(f"   Status: {job.status.state.name}")
        click.echo(f"   Created: {job.create_time}")

    except Exception as e:
        click.echo(f"❌ Failed to create job: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--labels", type=str, default="", help="Labels as key=value,key2=value2")
@click.option("--name", type=str, default="", help="Job name")
@click.option(
    "--since",
    type=str,
    default="1d",
    help="List jobs updated since a given time(days or hours) (e.g. 1h, 2h, 1d, 2d) (default: 1d)",
)
@click.option(
    "--status",
    type=click.Choice(
        [
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "QUEUED",
            "CANCELLED",
            "DELETION_IN_PROGRESS",
            "DELETED",
        ]
    ),
    help="Filter by job status",
)
@click.option("--page-size", type=int, default=100, help="Number of jobs to return")
@click.pass_context
def list_jobs(ctx, labels: str, name: str, since: str, status: str, page_size: int):
    """List Batch jobs with optional filtering by labels, name, time, and status."""
    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])
    labels_dict = None
    since_time = None
    name_filter = None
    status_filter = None

    try:
        if since:
            since_time = (
                datetime.now() - timedelta(days=int(since.split("d")[0]))
                if "d" in since
                else datetime.now() - timedelta(hours=int(since.split("h")[0]))
            )
        if labels:
            labels_dict = parse_labels(labels)
        if name:
            name_filter = name
        if status:
            status_filter = status

        jobs = client.list_jobs(
            labels=labels_dict,
            name=name_filter,
            since_time=since_time,
            status=status_filter,
            page_size=page_size,
        )

        if not jobs:
            click.echo("No jobs found matching the criteria.")
            return

        # Sort jobs by creation time (newest first)
        jobs = sorted(jobs, key=lambda job: job.create_time, reverse=True)

        click.echo(f"Found {len(jobs)} job(s):")
        click.echo("-" * 80)

        for job in jobs:
            click.echo(f"Name: {job.name.split('/')[-1]}")
            click.echo(f"Full Name: {job.name}")
            click.echo(f"Status: {job.status.state.name}")
            click.echo(f"Created: {job.create_time}")
            click.echo(f"Machine type: {job.allocation_policy.instances[0].policy.machine_type}")
            if job.labels:
                labels_dict = convert_labels_to_dict(job.labels)
                click.echo(f"Labels: {json.dumps(labels_dict, indent=2)}")
            click.echo("-" * 80)

    except Exception as e:
        click.echo(f"❌ Failed to list jobs: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--page-size", type=int, default=100, help="Number of jobs to return")
@click.option(
    "--since",
    type=str,
    help="List jobs created since a given time(days or hours) (e.g. 1h, 2h, 1d, 2d) (default: 1d)",
    default="1d",
)
@click.option(
    "--status",
    type=click.Choice(
        [
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "QUEUED",
            "CANCELLED",
            "DELETION_IN_PROGRESS",
            "DELETED",
        ]
    ),
    help="Filter by job status",
)
@click.pass_context
def list_my_jobs(ctx, page_size: int, since: str, status: str):
    """List jobs created by the current user with optional filtering by time and status."""
    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])
    created_by = resolve_created_by_label(ctx.obj["settings"].owner_email_env_vars)
    labels_dict = {"created-by": created_by}
    since_time = None
    status_filter = None
    if since:
        if "d" in since:
            days = int(since.split("d")[0])
            since_time = datetime.now() - timedelta(days=days)
        else:
            hours = int(since.split("h")[0])
            since_time = datetime.now() - timedelta(hours=hours)

    if status:
        status_filter = status
    try:
        jobs = client.list_jobs(
            labels=labels_dict,
            since_time=since_time,
            status=status_filter,
            page_size=page_size,
        )

        if not jobs:
            click.echo("No jobs found for the current user.")
            click.echo("Try creating a job first with: gc-batch create --help")
            return

        # Sort jobs by creation time (newest first)
        jobs = sorted(jobs, key=lambda job: job.create_time, reverse=True)

        click.echo("-" * 80)
        click.echo(f"Found {len(jobs)} job(s) for current user:")
        click.echo("Ordered by creation time (newest first).")

        for index, job in enumerate(jobs):
            click_centered_header(f" {index + 1} ")
            click.echo(f"Name: {job.name.split('/')[-1]}")
            click.echo(f"Full Name: {job.name}")
            click.echo(f"Status: {job.status.state.name}")
            click.echo(f"Created: {job.create_time}")
            if job.labels:
                labels_dict = convert_labels_to_dict(job.labels)
                click.echo(f"Labels: {json.dumps(labels_dict, indent=2)}")

        click.echo("-" * 80)
    except Exception as e:
        click.echo(f"❌ Failed to list jobs: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--job-name", required=True, help="Job name to check")
@click.option("--full", is_flag=True, default=False, help="Show full job details")
@click.pass_context
def status(ctx, job_name: str, full: bool):
    """Get status of a specific job."""
    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])

    try:
        job = client.get_job(job_name)

        click_centered_header("Job Details")
        click.echo(f"  Name: {job.name.split('/')[-1]}")
        click.echo(f"  Full Name: {job.name}")
        click.echo(f"  Status: {job.status.state.name}")
        click.echo(f"  Created: {job.create_time}")
        click.echo(f"  Updated: {job.update_time}")
        click.echo(f"  Machine type: {job.allocation_policy.instances[0].policy.machine_type}")

        if job.labels:
            labels_dict = convert_labels_to_dict(job.labels)
            click.echo(f"  Labels: {json.dumps(labels_dict, indent=2)}")

        # Show error details if failed
        if job.status.state.name == "FAILED":
            error_msg = client.get_failure_message(job)
            click_centered_header("Error Details")
            click.echo(f"{error_msg}")

        if full:
            click_centered_header("Full Job Details")
            # Convert the protobuf job object to JSON using MessageToJson
            job_json = MessageToJson(job._pb)
            click.echo(json.dumps(json.loads(job_json), indent=2))
        else:
            # Point at wherever this job's logs actually are: Cloud Logging has
            # nothing for jobs created with --logs-bucket.
            log_location = (
                GCSLogReader.resolve_log_location(job) if GCSLogReader.uses_gcs_logs(job) else None
            )
            if log_location is not None:
                click_centered_header("Logs (GCS)")
                click.echo(f"  This job writes logs to GCS, not Cloud Logging: {log_location.uri}")
            else:
                click_centered_header("Cloud Logging")
                click.echo(f"  View logs in console: {client.get_cloud_logging_url(job)}")
            click.echo("-" * 80)
            click.echo("To see full job details, run:")
            click.echo(f"  gc-batch status --job-name {job_name} --full")
            click.echo("To see detailed application logs, run:")
            click.echo(f"  gc-batch logs print --job-name {job_name}")
            if log_location is not None:
                click.echo(f"  (reads the logs straight from {log_location.uri})")

    except Exception as e:
        click.echo(f"❌ Failed to get job status: {e}", err=True)
        sys.exit(1)


def _log_failure_hints(error: Exception, job_writes_logs_to_gcs: bool) -> list[str]:
    """Return actionable hints for a log retrieval failure.

    Args:
        error: The failure raised while reading logs.
        job_writes_logs_to_gcs: Whether the job's logs are in a GCS bucket.

    Returns:
        Hint lines to print after the error, which may be empty.
    """
    is_permission_denied = isinstance(error, PermissionDenied) or "403" in str(error)
    if not is_permission_denied:
        return []
    if job_writes_logs_to_gcs:
        return [
            "   This caller cannot read the job's logs bucket. Check object read access "
            "to the bucket (and pass --logs-billing-project when it is requester-pays)."
        ]
    return [
        "   This caller cannot read Cloud Logging in this project, so no logs can be "
        "retrieved for jobs that write there.",
        "   Create jobs with --logs-bucket to have Batch write logs to a GCS bucket "
        "instead; `gc-batch logs print` and `logs download` then read them from the bucket.",
    ]


@cli.command()
@click.argument("command", type=click.Choice(["print", "download", "filter", "url"]))
@click.option("--job-name", default="", help="Job name to get logs for")
@click.option("--download-dir", default="", help="Directory to download logs to")
@click.option(
    "--severity",
    default="DEFAULT",
    help="Minimum severity level (DEFAULT, INFO, WARNING, ERROR)",
)
@click.pass_context
def logs(
    ctx,
    command: str,
    job_name: str,
    download_dir: str,
    severity: str,
):
    """View logs for a specific job."""

    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])

    if not job_name:
        click.echo("❌ --job_name must be provided")
        sys.exit(1)

    job = client.get_job(job_name)
    # Jobs created with --logs-bucket write to GCS instead of Cloud Logging, so the
    # job itself decides which reader can see its logs.
    reads_from_gcs = GCSLogReader.uses_gcs_logs(job)

    if command in ("print", "download"):
        if command == "download" and download_dir == "":
            download_dir = os.getcwd()
        try:
            if command == "print" and reads_from_gcs:
                client.gcs_logging.print_logs_for_job(job, severity)
            elif command == "print":
                client.batch_logging.print_logs_for_job(job, severity)
            elif reads_from_gcs:
                client.gcs_logging.download_logs_for_job(job, download_dir, severity)
            else:
                client.batch_logging.download_logs_for_job(job, download_dir, severity)
        except Exception as e:
            # A failed read is not an empty read: exit non-zero with the real cause.
            click.echo(f"❌ Failed to retrieve logs for job {job_name}: {e}", err=True)
            for hint in _log_failure_hints(e, reads_from_gcs):
                click.echo(hint, err=True)
            sys.exit(1)
    elif command == "filter":
        filter_string = client.batch_logging.get_filter_string_for_job(job, severity)
        if reads_from_gcs:
            click.echo(
                f"Note: this job writes logs to {GCSLogReader.resolve_log_location(job).uri}, "
                "not Cloud Logging, so this filter will match nothing."
            )
        click.echo(f"Filter string for job {job_name} with severity {severity}:")
        click.echo("-" * 80)
        click.echo(filter_string)
        click.echo("-" * 80)
    elif command == "url":
        logging_url = client.get_cloud_logging_url(job, severity)
        if reads_from_gcs:
            click.echo(
                f"Note: this job writes logs to {GCSLogReader.resolve_log_location(job).uri}, "
                "not Cloud Logging, so this query will return nothing."
            )
        click.echo(f"Cloud Logging URL for job {job_name}:")
        click.echo("-" * 80)
        click.echo(logging_url)
        click.echo("-" * 80)


@cli.command()
@click.pass_context
def show_config(ctx):
    """Print the resolved gc-batch settings (for debugging config precedence)."""
    settings = ctx.obj["settings"]
    click.echo(json.dumps(settings.model_dump(), indent=2, default=str))


@cli.command()
@click.option("--job-name", required=True, help="Job name to delete")
@click.pass_context
def cancel(ctx, job_name: str):
    """Delete a Batch job."""
    client = create_client(ctx.obj["location"], _require_project_id(ctx), ctx.obj["settings"])

    try:
        # First get the job to confirm it exists
        job = client.get_job(job_name)
        click.echo(f"Cancelling job: {job.name} (UID: {job.uid})")

        client.cancel_job(job.name)

    except Exception as e:
        click.echo(f"❌ Failed to cancel job: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
