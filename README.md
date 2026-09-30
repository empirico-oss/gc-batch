# gc-batch

A command-line interface and Python client for managing Google Cloud Batch jobs,
with support for job creation, monitoring, logging, GCS bucket mounts, local SSD
storage, and filtering by labels.

## Installation

```bash
pip install gc-batch
```

Or, for development, using [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/empirico-oss/gc-batch.git
cd gc-batch
uv sync
```

Requires Python 3.10 or newer, and credentials for a Google Cloud project with the
Batch API enabled (`gcloud auth application-default login`).

## Quick start

```bash
# Create a job
gc-batch --project-id my-project create \
  --job-name my-first-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py"

# List jobs, or just your own
gc-batch --project-id my-project list-jobs
gc-batch --project-id my-project list-my-jobs

# Check status and read logs
gc-batch --project-id my-project status --job-name my-first-job-1234567890
gc-batch --project-id my-project logs --job-name my-first-job-1234567890
```

The project is resolved from `--project-id`, then `$GOOGLE_PROJECT`, then the
`default_project_id` setting. If none is set, the command exits with an error
rather than guessing.

## Use as a Python library

The same functionality is importable, so scripts, notebooks, and orchestration
code can submit and monitor jobs without shelling out to the CLI:

```python
import time

from gc_batch import BatchClientConfig, BatchJobConfig, GCBatchClient, JobRequest
from gc_batch.utils import is_job_finished

client = GCBatchClient(BatchClientConfig(project_id="my-project", location="us-central1"))

job = client.create_job(
    JobRequest(
        job_name="my-first-job",
        docker_image="gcr.io/my-project/my-image:latest",
        command="python /app/main.py",
        config=BatchJobConfig(
            machine_type="n2-standard-4",
            boot_disk_type="pd-balanced",
            input_bucket="my-bucket/datasets",
            output_bucket="my-bucket/results",
        ),
        labels={"team": "data-science"},
    )
)

# create_job timestamps the name, so read the submitted one off the job
short_name = job.name.split("/")[-1]

while not is_job_finished(job := client.get_job(short_name)):
    time.sleep(30)

print(job.status.state.name)
if job.status.state.name == "FAILED":
    print(client.get_failure_message(job))
    print(client.get_cloud_logging_url(job, severity="ERROR"))
```

Listing, cancelling, and log retrieval are all available too:

```python
jobs = client.list_jobs(labels={"team": "data-science"}, status="RUNNING")
client.cancel_job(job.name)  # full resource path, not the short name

# Logs, from Cloud Logging or from the bucket when the job used logs_bucket
client.batch_logging.print_logs_for_job(job)
client.gcs_logging.print_logs_for_job(job)
```

See the [Python API guide](docs/guides/python-api.md) for job profiles, mounts,
local SSD, settings, fan-out, and error handling.

## Configuration

Values that differ between deployments — the job-name prefix, the
`created-using` label, and named job profiles — are resolved in this order,
highest precedence first:

1. explicit arguments
2. `GC_BATCH_*` environment variables
3. a TOML config file (`--config-file`, `$GC_BATCH_CONFIG_FILE`, `./gc-batch.toml`,
   or `$XDG_CONFIG_HOME/gc-batch/config.toml`)
4. neutral defaults

### Restricted VPC environments

`gc-batch` ships a built-in `all-of-us` job profile for the
[All of Us](https://allofus.nih.gov/) Researcher Workbench, which runs jobs inside
a restricted VPC:

```bash
gc-batch --project-id my-project create \
  --job-profile all-of-us \
  --job-name my-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py"
```

You can define additional profiles in the config file. See the
[Configuration guide](docs/guides/configuration.md).

## Documentation

Full documentation: https://empirico-oss.github.io/gc-batch/stable/

- [Quick Start](docs/guides/quick-start.md)
- [Commands Reference](docs/guides/commands.md)
- [Python API](docs/guides/python-api.md)
- [Input/Output Mounts](docs/guides/mounts.md)
- [Local SSD Storage](docs/guides/local-ssd.md)
- [Label Management](docs/guides/labels.md)
- [Configuration](docs/guides/configuration.md)
- [Troubleshooting](docs/guides/troubleshooting.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues should be reported per
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
