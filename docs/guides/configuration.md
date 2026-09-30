# Configuration

gc-batch uses sensible defaults but allows you to override settings via command-line options and environment variables.


## Default Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Location | `us-central1` | GCP region for Batch jobs |
| Project ID | _none_ | GCP project, from `--project-id`, `$GOOGLE_PROJECT`, or the `default_project_id` setting. Required. |
| Machine Type | `e2-standard-2` | VM machine type |
| Boot Disk Size | `30` GB | Size of the boot disk |
| Boot Disk Type | `pd-balanced` | Type of boot disk |
| Input Directory | `/mnt/input` | Container mount point for input |
| Output Directory | `/mnt/output` | Container mount point for output |


## Environment Variables

### GCP Configuration

| Variable | Description |
|----------|-------------|
| `GOOGLE_PROJECT` | Default GCP project ID (used if `--project-id` not specified) |
| `USER` | Used for the `created-by` label (default; see `owner_email_env_vars`) |
| `GC_BATCH_*` | Override any setting; see [Settings file](#settings-file) |

### Container Environment Variables

When you create a job with input/output mounts, gc-batch automatically sets these environment variables in your container:

| Variable | Description | Example |
|----------|-------------|---------|
| `INPUT_DIR` | Path to input mount | `/mnt/input` |
| `OUTPUT_DIR` | Path to output mount | `/mnt/output` |

Use these in your application:

```python
import os

input_dir = os.environ.get("INPUT_DIR", "/mnt/input")
output_dir = os.environ.get("OUTPUT_DIR", "/mnt/output")

# Read from input
with open(f"{input_dir}/data.csv") as f:
    data = f.read()

# Write to output
with open(f"{output_dir}/results.json", "w") as f:
    f.write(results)
```


## Override Defaults

### Change Location and Project

```bash
# Use different location and project
gc-batch --location us-west1 --project-id my-other-project list-jobs

# Create job in different region
gc-batch --location europe-west1 create \
  --job-name eu-job \
  --docker-image python:3.12 \
  --command "python main.py"
```

### Change Machine Type

```bash
# Use a larger machine
gc-batch create \
  --job-name big-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type n2-standard-8

# Use a high-memory machine
gc-batch create \
  --job-name memory-intensive \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type n2-highmem-4
```

### Change Disk Settings

```bash
# Larger boot disk
gc-batch create \
  --job-name big-disk \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --boot-disk-size 100

# Use SSD boot disk
gc-batch create \
  --job-name fast-boot \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --boot-disk-type pd-ssd
```


## Provisioning Models

Control cost vs availability with provisioning models:

| Model | Cost | Availability | Use Case |
|-------|------|--------------|----------|
| `STANDARD` | Highest | Guaranteed | Production, time-sensitive jobs |
| `SPOT` | 60-91% cheaper | May be preempted | Fault-tolerant batch jobs |
| `PREEMPTIBLE` | Similar to SPOT | May be preempted | Legacy (use SPOT instead) |

### Using SPOT for Cost Savings

```bash
gc-batch create \
  --job-name cost-optimized \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/process.py" \
  --provisioning-model SPOT
```

!!! tip "When to use SPOT"
    Use SPOT VMs for:
    
    - Batch processing that can be retried
    - Development and testing
    - Non-urgent data processing
    - Any workload that can handle interruptions

!!! warning "SPOT Limitations"
    SPOT VMs can be preempted (terminated) at any time if Google Cloud needs the capacity.
    Your job should be able to handle restarts or save progress periodically.


## Custom Environment Variables

Pass custom environment variables to your container:

```bash
gc-batch create \
  --job-name env-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --env "DATABASE_URL=postgres://...,API_KEY=abc123,DEBUG=true"
```

Access in your container:

```python
import os

database_url = os.environ.get("DATABASE_URL")
api_key = os.environ.get("API_KEY")
debug = os.environ.get("DEBUG", "false").lower() == "true"
```


## Settings file

Values that differ between deployments are resolved in this order, highest
precedence first:

1. explicit arguments (CLI options, or constructor arguments in the Python API)
2. `GC_BATCH_*` environment variables
3. a TOML config file
4. neutral defaults

The config file is discovered from `--config-file`, then `$GC_BATCH_CONFIG_FILE`,
then `./gc-batch.toml`, then `$XDG_CONFIG_HOME/gc-batch/config.toml`.

```toml
# gc-batch.toml
default_project_id  = "my-project"
job_name_prefix     = ""          # prepended to every job name
created_using_label = "gc-batch"  # value of the created-using label

# Environment variables checked, in order, for the created-by label
owner_email_env_vars = ["USER"]

# Additional named job profiles, usable via --job-profile
[job_profiles.my-vpc]
network             = "global/networks/my-network"
subnetwork          = "regions/us-central1/subnetworks/my-subnet"
use_private_address = true
regions             = ["us-central1"]
```

Run the config-display command to see the resolved settings and debug precedence.


## Job profiles

A job profile is a named bundle of network and placement settings applied with
`--job-profile <name>`. Passing an unknown name is an error that lists the
available profiles.

### The built-in `all-of-us` profile

`gc-batch` ships one built-in profile for the
[All of Us](https://allofus.nih.gov/) Researcher Workbench, whose jobs run inside
a restricted VPC. `--job-profile all-of-us` applies:

- `network` = `global/networks/network`
- `subnetwork` = `regions/us-central1/subnetworks/subnetwork`
- `use_private_address` = `true`
- `regions` = `["us-central1"]`
- `service_account` taken from your current `gcloud` authentication
- `cloud_logging_unreadable` = `true`

```bash
gc-batch --project-id my-project create \
  --job-profile all-of-us \
  --job-name my-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py"
```

!!! warning "Set `--logs-bucket` in the All of Us workbench"
    Workspace service accounts cannot read Cloud Logging, so a job that writes its
    logs there produces logs nobody in the workspace can read. Because
    `cloud_logging_unreadable` is `true` for this profile, `create` warns when
    `--logs-bucket` is missing. Heed it: the log destination is fixed when the job is
    created, so the only remedy afterwards is to recreate the job.

### Declaring that Cloud Logging is unreadable

Set `cloud_logging_unreadable = true` on any profile whose environment cannot read
Cloud Logging, and `create` will warn when `--logs-bucket` is omitted:

```toml
[job_profiles.locked-down]
network                  = "global/networks/my-network"
use_private_address      = true
cloud_logging_unreadable = true
```

The warning is advisory — it goes to stderr and does not stop the job from being
created.

