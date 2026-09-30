# Python API

Everything the `gc-batch` CLI does is also available as a Python library, so you can
submit and monitor Batch jobs from a script, a notebook, or your own orchestration
code without shelling out to the CLI.

The pieces you will use most:

| Object | Purpose |
| --- | --- |
| [`GCBatchClient`](../reference/gc_batch/client.md) | Create, list, inspect, and cancel jobs |
| [`BatchClientConfig`](../reference/gc_batch/models/batch_config.md) | Project, location, and deployment settings for the client |
| [`BatchJobConfig`](../reference/gc_batch/models/job_request.md) | Machine type, disks, mounts, networking, environment |
| [`JobRequest`](../reference/gc_batch/models/job_request.md) | One job: name, image, command, config, labels |
| [`GCBatchSettings`](../reference/gc_batch/settings.md) | Deployment values (job-name prefix, job profiles) |
| [`BatchLogging`](../reference/gc_batch/batch_logging.md) | Read job logs from Cloud Logging |
| [`GCSLogReader`](../reference/gc_batch/gcs_logging.md) | Read job logs written to a GCS bucket |


## Submitting a job

```python
from gc_batch import BatchClientConfig, BatchJobConfig, GCBatchClient, JobRequest

client = GCBatchClient(BatchClientConfig(project_id="my-project", location="us-central1"))

job = client.create_job(
    JobRequest(
        job_name="hello-world",
        docker_image="python:3.12-slim",
        command="python -c 'print(\"Hello from Batch\")'",
        config=BatchJobConfig(
            machine_type="e2-standard-2",
            boot_disk_type="pd-balanced",
        ),
    )
)

print(job.name)  # projects/my-project/locations/us-central1/jobs/hello-world-1758412800
```

`machine_type` and `boot_disk_type` are the only required fields on
`BatchJobConfig`. Disk-type support varies by machine generation, so let
`MachineTypeHelper` pick one if you are generating configs programmatically:

```python
from gc_batch import MachineTypeHelper

machine_type = "c4-standard-8"
config = BatchJobConfig(
    machine_type=machine_type,
    boot_disk_type=MachineTypeHelper.get_default_disk_type(machine_type),
)
```

!!! note "Job names get a timestamp"

    `create_job` appends a Unix timestamp to `job_name` (and prepends
    `settings.job_name_prefix` when configured), so the submitted name is not the
    one you passed. Read the real name off the returned job — either
    `job.name` for the full resource path or `job.name.split("/")[-1]` for the
    short name that `get_job` and the CLI expect.


## Labels

`create_job` always sets four labels: `job-name`, `created-using` (from
`settings.created_using_label`), `created-by`, and `created-at`. Anything in
`JobRequest.labels` is merged on top, so an explicit label wins over the default.

```python
request = JobRequest(
    job_name="nightly-rollup",
    docker_image="gcr.io/my-project/rollup:latest",
    command="python /app/rollup.py",
    config=config,
    labels={"team": "data-science", "environment": "production"},
)
```

`created-by` is what `gc-batch list-my-jobs` filters on. It is resolved from the
first environment variable in `settings.owner_email_env_vars` that is set
(`$OWNER_EMAIL`, `$WORKBENCH_USER_EMAIL`, `$TERRA_USER_EMAIL`, then `$USER` by
default), reduced to the local part of an email address — so
`jane.doe@example.com` becomes `jane-doe`, and it falls back to `unknown` when
none are set. Jobs you submit from the library are therefore findable with
`list-my-jobs` just like CLI-submitted ones.

For code that runs unattended, where no user identity applies, set it explicitly:

```python
labels = {"team": "data-science", "created-by": "nightly-pipeline"}
```

You can resolve the same value yourself, which is how you would build a
`list_jobs` filter that matches the current user:

```python
from gc_batch.utils import resolve_created_by_label

created_by = resolve_created_by_label(client.config.settings.owner_email_env_vars)
my_jobs = client.list_jobs(labels={"created-by": created_by})
```

Label values must match GCP's rules: lowercase letters, numbers, `-`, and `_`.


## Waiting for a job to finish

There is no blocking `wait` call; poll `get_job` and check the state with
`is_job_finished`:

```python
import time

from gc_batch.utils import is_job_finished

short_name = job.name.split("/")[-1]

while True:
    job = client.get_job(short_name)
    if is_job_finished(job):
        break
    time.sleep(30)

print(job.status.state.name)  # SUCCEEDED, FAILED, CANCELLED, ...

if job.status.state.name == "FAILED":
    print(client.get_failure_message(job))
```

`get_failure_message` summarizes the state, the most relevant failure event, the
failed-task count, and the job UID — the same summary `gc-batch status --full`
prints.


## Listing and filtering jobs

```python
from datetime import datetime, timedelta, timezone

# Everything in the project/location
all_jobs = client.list_jobs()

# By label
team_jobs = client.list_jobs(labels={"team": "data-science"})

# Failed in the last day
recent_failures = client.list_jobs(
    status="FAILED",
    since_time=datetime.now(timezone.utc) - timedelta(days=1),
)

# Combined filters
jobs = client.list_jobs(
    labels={"team": "data-science", "environment": "production"},
    status="RUNNING",
    page_size=500,
)

for job in jobs:
    print(job.name.split("/")[-1], job.status.state.name)
```

`labels`, `status`, and `since_time` are pushed into the Batch API filter.
`name` is applied client-side (the Batch API has no name filter), so it narrows
an already-fetched page rather than reducing what is fetched.


## Cancelling a job

`cancel_job` takes the **full** resource path, not the short name:

```python
job = client.get_job("nightly-rollup-1758412800")
client.cancel_job(job.name)
```


## Logs

A job's logs live in one of two places, fixed when the job is created: Cloud
Logging by default, or a GCS bucket when `logs_bucket` was set. Each has a reader
on the client — `client.batch_logging` for Cloud Logging and `client.gcs_logging`
for a bucket — and both expose the same `print_logs_for_job` /
`download_logs_for_job` methods:

```python
job = client.get_job("nightly-rollup-1758412800")

# Print to stdout
client.batch_logging.print_logs_for_job(job)

# Only warnings and above
client.batch_logging.print_logs_for_job(job, severity="WARNING")

# Write <job-name>.log into a directory
client.batch_logging.download_logs_for_job(job, download_dir="./logs")

# A Cloud Console link, handy to put in a Slack message or a dashboard
print(client.get_cloud_logging_url(job, severity="ERROR"))
```

Both readers return the number of entries handled, so zero is a successful read of
an empty log rather than a failure, and both raise on an API error instead of
printing it — see [Errors](#errors).

To handle a job either way, ask which route it uses. This is exactly what
`gc-batch logs print` does:

```python
from gc_batch.gcs_logging import GCSLogReader

reader = client.gcs_logging if GCSLogReader.uses_gcs_logs(job) else client.batch_logging
entry_count = reader.print_logs_for_job(job)
if entry_count == 0:
    print("The job produced no log entries.")
```

For the entries themselves rather than printed output, `client.gcs_logging` has
`read_logs_for_job`, which returns dicts with `timestamp`, `severity`,
`textPayload`, `jsonPayload`, and `resource` keys:

```python
for entry in client.gcs_logging.read_logs_for_job(job, severity="ERROR"):
    print(entry["timestamp"], entry["textPayload"])

# Where the logs actually are, without reading them
print(GCSLogReader.resolve_log_location(job).uri)  # gs://my-bucket/batch-logs/<job>/
```

Entries come back in the order Batch wrote them — objects within a task, tasks in
index order, `stdout` before `stderr` — not re-sorted by timestamp, because Batch
timestamps have only one-second resolution.

### Choosing the destination

Set `logs_bucket` to route logs to GCS. Batch supports a single destination, so
this turns Cloud Logging off for that job:

```python
config = BatchJobConfig(
    machine_type="e2-standard-2",
    boot_disk_type="pd-balanced",
    logs_bucket="my-bucket/batch-logs",
)
```

Logs then land under `gs://my-bucket/batch-logs/<timestamped-job-name>/`, and
`client.gcs_logging` reads them. This is the route to use where the caller has no
Cloud Logging read access at all — a restricted-VPC environment, where querying
Cloud Logging returns `403 Permission denied for all log views`. Since the
destination cannot be changed after creation, decide before submitting.


## Mounts, local SSD, and environment

`BatchJobConfig` covers the same ground as the `create` flags:

```python
config = BatchJobConfig(
    machine_type="n2-standard-8",
    boot_disk_type="pd-balanced",
    boot_disk_size=100,
    # GCS buckets mounted into the container (no gs:// prefix)
    input_bucket="my-bucket/datasets",
    input_dir="/mnt/input",
    output_bucket="my-bucket/results",
    output_dir="/mnt/output",
    # Scratch space; size must be a multiple of 375 GB
    local_ssd_size_gb=375,
    local_ssd_mount_path="/mnt/scratch",
    # SPOT VMs for non-urgent work
    provisioning_model="SPOT",
    # Environment variables for the container
    user_env_dict={"LOG_LEVEL": "DEBUG", "MAX_WORKERS": "4"},
)

request = JobRequest(
    job_name="analysis",
    docker_image="gcr.io/my-project/analyzer:latest",
    command="python /app/analyze.py",
    args="--input /mnt/input/data.csv --output /mnt/output/results/",
    config=config,
)
```

For requester-pays buckets, set `input_billing_project` / `logs_billing_project`.
LSSD machine types (for example `c4-standard-8-lssd`) come with SSDs attached, so
set `local_ssd_mount_path` but leave `local_ssd_size_gb` unset — passing both
raises `ValueError`.

See [Input/Output Mounts](mounts.md) and [Local SSD Storage](local-ssd.md) for the
details behind these fields.


## Settings and job profiles

`BatchClientConfig.settings` holds the deployment-specific values. Constructing
`GCBatchSettings` directly uses environment variables and defaults only;
`GCBatchSettings.load()` also reads the TOML config file:

```python
from gc_batch import BatchClientConfig, GCBatchClient, GCBatchSettings

settings = GCBatchSettings.load()  # ./gc-batch.toml, $GC_BATCH_CONFIG_FILE, XDG path
client = GCBatchClient(
    BatchClientConfig(
        project_id=settings.default_project_id or "my-project",
        location="us-central1",
        settings=settings,
    )
)
```

Or set them inline, skipping config-file discovery entirely:

```python
settings = GCBatchSettings(
    job_name_prefix="team-a-",
    created_using_label="my-pipeline",
)
```

Job profiles are bundles of networking/VM settings — what the CLI applies for
`--job-profile`. In library code, apply one with `BatchJobConfig.apply_profile`:

```python
from gc_batch import BatchJobConfig, GCBatchSettings

settings = GCBatchSettings.load()
profile = settings.job_profiles["all-of-us"]  # built-in; add your own via config

config = BatchJobConfig(
    machine_type="n2-standard-4",
    boot_disk_type="pd-balanced",
).apply_profile(profile)
```

`apply_profile` mutates the config in place and returns it, so it works either
chained (as above) or as a statement on an existing config. Fields the profile
leaves unset are untouched, so you can apply a profile over a config that already
has other settings. When the profile sets `service_account_from_gcloud`, the
service account is resolved from the active `gcloud` account and a `ValueError` is
raised if there isn't one:

```python
try:
    config.apply_profile(profile)
except ValueError as error:
    print(f"{error}")  # ... Please run `gcloud auth login`.
```

A profile's `cloud_logging_unreadable` flag is advisory rather than a job setting,
so `apply_profile` does not act on it. It marks environments where Cloud Logging
cannot be read; the CLI warns when such a profile is used without `--logs-bucket`,
and library code can make the same check:

```python
if profile.cloud_logging_unreadable and not config.logs_bucket:
    raise RuntimeError("Set logs_bucket, or this job's logs will be unreadable.")
```

See [Configuration](configuration.md) for defining your own profiles.


## Fanning out over many inputs

Submission is cheap and non-blocking, so the usual pattern is to submit a job per
input and then poll the batch of them:

```python
import time

from gc_batch import BatchClientConfig, BatchJobConfig, GCBatchClient, JobRequest
from gc_batch.utils import is_job_finished

SAMPLES = ["SAMPLE_001", "SAMPLE_002", "SAMPLE_003"]

client = GCBatchClient(BatchClientConfig(project_id="my-project", location="us-central1"))

submitted = []
for sample in SAMPLES:
    config = BatchJobConfig(
        machine_type="n2-highmem-8",
        boot_disk_type="pd-balanced",
        boot_disk_size=500,
        input_bucket=f"my-genomics-bucket/raw-samples/{sample}",
        output_bucket=f"my-genomics-bucket/processed/{sample}",
    )
    job = client.create_job(
        JobRequest(
            job_name=f"sequence-{sample.lower().replace('_', '-')}",
            docker_image="gcr.io/my-project/sequencing:latest",
            command="python /app/sequence.py",
            args=f"--sample-id {sample} --reference hg38",
            config=config,
            labels={"project": "genomics", "sample": sample.lower().replace("_", "-")},
        )
    )
    submitted.append(job.name.split("/")[-1])

pending = set(submitted)
results = {}
while pending:
    for short_name in list(pending):
        job = client.get_job(short_name)
        if is_job_finished(job):
            results[short_name] = job.status.state.name
            pending.discard(short_name)
    if pending:
        time.sleep(30)

failed = [name for name, state in results.items() if state != "SUCCEEDED"]
print(f"{len(results) - len(failed)}/{len(results)} succeeded")
```

Since each submitted job carries your labels, you can also poll the whole set
with one API call instead of one per job:

```python
jobs = client.list_jobs(labels={"project": "genomics"}, status="RUNNING")
print(f"{len(jobs)} still running")
```


## Errors

The client logs and re-raises the underlying `google-cloud-batch` exceptions, so
handle them as you would any GCP API call. Configuration mistakes surface earlier,
as `pydantic.ValidationError` when the models are constructed:

```python
from google.api_core import exceptions as gcp_exceptions
from pydantic import ValidationError

try:
    config = BatchJobConfig(machine_type="n2-standard-4", boot_disk_type="not-a-disk")
except ValidationError as error:
    print(f"Bad job config: {error}")

try:
    job = client.create_job(request)
except gcp_exceptions.PermissionDenied as error:
    print(f"Check your credentials and project: {error}")
```

Log retrieval raises too, rather than reporting a failure as an empty log, so a
permission problem is distinguishable from a job that printed nothing:

```python
try:
    entry_count = client.batch_logging.print_logs_for_job(job)
except gcp_exceptions.PermissionDenied:
    # Normal in restricted environments; such jobs need logs_bucket instead.
    print("No Cloud Logging read access in this project.")
else:
    if entry_count == 0:
        print("The job produced no log entries.")
```

`client.gcs_logging` additionally raises `ValueError` if the job does not write its
logs to a bucket, which is what `GCSLogReader.uses_gcs_logs(job)` checks for.

Pass your own logger if you want the client's output to go through your
application's logging setup:

```python
import logging

client = GCBatchClient(
    BatchClientConfig(project_id="my-project", location="us-central1"),
    log_level=logging.DEBUG,
)
```


## Full API reference

The generated reference documents every model field and method:

- [`gc_batch.client`](../reference/gc_batch/client.md)
- [`gc_batch.models.job_request`](../reference/gc_batch/models/job_request.md)
- [`gc_batch.models.batch_config`](../reference/gc_batch/models/batch_config.md)
- [`gc_batch.batch_logging`](../reference/gc_batch/batch_logging.md)
- [`gc_batch.gcs_logging`](../reference/gc_batch/gcs_logging.md)
- [`gc_batch.settings`](../reference/gc_batch/settings.md)
- [`gc_batch.utils`](../reference/gc_batch/utils.md)
