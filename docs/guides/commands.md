---
title: Commands Reference
---

# Commands Reference

Complete reference for all gc-batch CLI commands.

## Global Options

All commands support these global options:

| Option | Description | Default |
|--------|-------------|---------|
| `--location` | GCP location | `us-central1` |
| `--project-id` | GCP project ID (or `$GOOGLE_PROJECT`, or `default_project_id`) | `my-project` |


## create

Create a new Google Cloud Batch job.

```bash
gc-batch create [OPTIONS]
```

### Required Options

| Option | Description |
|--------|-------------|
| `--job-name` | Name for the job |
| `--docker-image` | Docker image to use |
| `--command` | Command to run |

### Optional Options

| Option | Description | Default |
|--------|-------------|---------|
| `--args` | Command arguments | - |
| `--labels` | Labels as `key=value,key2=value2` | - |
| `--task-count` | Number of tasks | `1` |
| `--parallelism` | Parallelism level | `1` |
| `--machine-type` | Machine type | `e2-standard-2` |
| `--provisioning-model` | `STANDARD`, `SPOT`, or `PREEMPTIBLE` | `STANDARD` |
| `--disk-size` | Disk size in GB | `200` |
| `--disk-type` | Disk type | `pd-balanced` |
| `--boot-disk-size` | Boot disk size in GB | `30` |
| `--data-disk-size` | Data disk size in GB | `200` |
| `--data-disk-type` | Data disk type | `pd-balanced` |

### Input/Output Mount Options

| Option | Description | Default |
|--------|-------------|---------|
| `--input-bucket` | GCS bucket path for input data | - |
| `--input-dir` | Mount point for input data | `/mnt/input` |
| `--input-billing-project` | Billing project for requester-pays buckets | - |
| `--output-bucket` | GCS bucket path for output data | - |
| `--output-dir` | Mount point for output data | `/mnt/output` |
| `--logs-bucket` | GCS bucket path to write job logs to (replaces Cloud Logging) | - |
| `--logs-billing-project` | Billing project for requester-pays logs bucket | - |

### Local SSD Options

| Option | Description | Default |
|--------|-------------|---------|
| `--local-ssd-size-gb` | Size of local SSD (must be multiple of 375 GB) | - |
| `--local-ssd-device-name` | Device name for the local SSD | `local-ssd-0` |
| `--local-ssd-mount-path` | Mount path for the local SSD | `/mnt/disks/{device_name}` |

### Examples

```bash
# Basic job creation
gc-batch create \
  --job-name data-analysis \
  --docker-image gcr.io/my-project/analysis:latest \
  --command "python /app/analyze.py"

# Advanced job with labels and data mounts
gc-batch create \
  --job-name genome-sequencing \
  --docker-image gcr.io/my-project/sequencing:latest \
  --command "python /app/sequence.py" \
  --args "--sample-id SAMPLE_001" \
  --input-bucket my-genomics-bucket/raw-samples \
  --output-bucket my-genomics-bucket/processed-results \
  --labels "environment=production,team=bioinformatics" \
  --machine-type n2-standard-4 \
  --disk-size 500

# Job with SPOT provisioning for cost savings
gc-batch create \
  --job-name cost-optimized-job \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --provisioning-model SPOT \
  --machine-type e2-standard-2

# Job with local SSD for high-performance I/O
gc-batch create \
  --job-name high-io-job \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --machine-type n2-standard-4 \
  --local-ssd-size-gb 375 \
  --local-ssd-mount-path /mnt/disks/fast-storage
```


## list-jobs

List and filter Batch jobs.

```bash
gc-batch list-jobs [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--labels` | Filter by labels as `key=value,key2=value2` | - |
| `--name` | Filter by job name | - |
| `--since` | Filter by creation time (`1h`, `2h`, `1d`, `2d`) | `1d` |
| `--status` | Filter by status | - |
| `--page-size` | Number of jobs to return | `100` |

### Status Values

- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `QUEUED`
- `CANCELLED`
- `DELETION_IN_PROGRESS`
- `DELETED`

### Examples

```bash
# List all jobs
gc-batch list-jobs

# List jobs with specific labels
gc-batch list-jobs --labels "environment=production,team=data-science"

# List failed jobs from the last 2 days
gc-batch list-jobs --status FAILED --since 2d

# List jobs by name pattern
gc-batch list-jobs --name "data-analysis"

# Combine multiple filters
gc-batch list-jobs --labels "team=data-science" --status RUNNING --since 1d
```


## list-my-jobs

List jobs created by the current user.

```bash
gc-batch list-my-jobs [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--since` | Filter by creation time | `1d` |
| `--status` | Filter by job status | - |
| `--page-size` | Number of jobs to return | `100` |

### Examples

```bash
# List all my jobs
gc-batch list-my-jobs

# List my failed jobs from the last week
gc-batch list-my-jobs --since 7d --status FAILED

# List my running jobs
gc-batch list-my-jobs --status RUNNING
```


## status

Get detailed status information for a specific job.

```bash
gc-batch status --job-name JOB_NAME [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--job-name` | Name of the job (required) |
| `--full` | Show complete job details as JSON |

### Examples

```bash
# Basic status check
gc-batch status --job-name my-job-1234567890

# Full job details (JSON format)
gc-batch status --job-name my-job-1234567890 --full
```

### Output Includes

- Job name and full path
- Current status
- Creation and update times
- Labels
- Task group status
- Error details (if failed)
- Full job configuration (with `--full` flag)


## logs

View logs for a specific job.

```bash
gc-batch logs COMMAND --job-name JOB_NAME [OPTIONS]
```

### Subcommands

| Command | Description |
|---------|-------------|
| `print` | Print logs to console |
| `download` | Download logs to local directory |
| `filter` | Get the filter string for Cloud Logging queries |
| `url` | Get a URL to view logs in Google Cloud Console |

### Log source

`print` and `download` read from wherever the job actually wrote its logs, which is decided when the job is created:

- Jobs created **without** `--logs-bucket` write to Cloud Logging, which is queried.
- Jobs created **with** `--logs-bucket` write to that bucket (see [Sending logs to a GCS bucket](mounts.md#sending-logs-to-a-gcs-bucket)); the bucket is read instead, so these commands work even where Cloud Logging is unreadable. The bucket and prefix are recovered from the job itself, so there is nothing extra to pass.

`filter` and `url` always describe Cloud Logging. For a job that writes to a bucket they print a note saying the query will match nothing.

### Exit codes

| Situation | Exit code | Output |
|-----------|-----------|--------|
| Logs retrieved | 0 | The log entries |
| Retrieval succeeded, nothing matched | 0 | `No log entries matched …` |
| Retrieval failed (e.g. no permission to read logs) | 1 | The underlying error, plus how to work around it |

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--job-name` | Name of the job (required) | - |
| `--download-dir` | Directory to download logs to | `.` |
| `--severity` | Minimum severity (`DEFAULT`, `DEBUG`, `INFO`, `NOTICE`, `WARNING`, `ERROR`, `CRITICAL`, `ALERT`, `EMERGENCY`) | `DEFAULT` |

### Examples

```bash
# Print logs to console
gc-batch logs print --job-name my-job-1234567890

# Download logs to current directory
gc-batch logs download --job-name my-job-1234567890

# Download logs to specific directory
gc-batch logs download --job-name my-job-1234567890 --download-dir ./my-logs

# Get Cloud Logging URL for the job
gc-batch logs url --job-name my-job-1234567890

# Get Cloud Logging URL filtered to show only errors
gc-batch logs url --job-name my-job-1234567890 --severity ERROR
```


## cancel

Cancel a running or pending job.

```bash
gc-batch cancel --job-name JOB_NAME
```

### Examples

```bash
gc-batch cancel --job-name my-job-1234567890
```


## Label Filters

The CLI supports filtering by labels in various ways:

```bash
# Using --labels option (simpler)
--labels "environment=production,team=data-science"

# Using --filter option (more powerful)
--filter 'labels.environment="production"'
--filter 'labels.team="data-science" AND labels.environment="staging"'
```


## Other Filters

```bash
# Job name pattern
--filter 'name:genome-sequencing'

# Status filter
--filter 'status.state="RUNNING"'

# Time-based filter
--filter 'createTime>="2024-01-01T00:00:00Z"'

# Complex combinations
--filter 'labels.environment="production" AND createTime>="2024-01-01T00:00:00Z" AND status.state="RUNNING"'
```
