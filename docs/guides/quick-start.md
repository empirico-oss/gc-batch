# Quick Start Guide

This guide walks you through creating and managing your first Google Cloud Batch job.


## Prerequisites

Before starting, ensure you have:

1. **gc-batch installed**: See [Getting Started](../development/index.md)
2. **GCP authentication**: Run `gcloud auth login`
3. **A Docker image**: Either use a public image or build your own


## Creating Your First Job

### Basic Job

Create a simple job that runs a Python script:

```bash
gc-batch create \
  --job-name hello-world \
  --docker-image python:3.12-slim \
  --command "python -c 'print(\"Hello from Google Cloud Batch!\")'"
```

### Job with Custom Image

If you have your own Docker image:

```bash
gc-batch create \
  --job-name my-analysis \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --args "--input-file data.csv"
```


## Monitoring Your Job

### Check Status

```bash
gc-batch status --job-name hello-world-1234567890
```

The status will show:
- **QUEUED**: Job is waiting for resources
- **RUNNING**: Job is currently executing
- **SUCCEEDED**: Job completed successfully
- **FAILED**: Job failed (check logs for details)

### View Logs

```bash
# Print logs to console
gc-batch logs print --job-name hello-world-1234567890

# Get a URL to view in Cloud Console
gc-batch logs url --job-name hello-world-1234567890
```


## Listing Jobs

### List All Recent Jobs

```bash
gc-batch list-jobs --since 1d
```

### List Your Jobs Only

```bash
gc-batch list-my-jobs
```

### Filter by Status

```bash
# Running jobs
gc-batch list-jobs --status RUNNING

# Failed jobs from the last week
gc-batch list-jobs --status FAILED --since 7d
```


## Canceling a Job

If you need to stop a running job:

```bash
gc-batch cancel --job-name hello-world-1234567890
```


## Adding Labels

Labels help organize and filter your jobs:

```bash
gc-batch create \
  --job-name labeled-job \
  --docker-image python:3.12-slim \
  --command "python -c 'print(1+1)'" \
  --labels "team=data-science,environment=dev,project=testing"
```

Then filter by labels:

```bash
gc-batch list-jobs --labels "team=data-science"
```


## Using Different Machine Types

### Larger Machine

For compute-intensive workloads:

```bash
gc-batch create \
  --job-name big-compute \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/heavy_computation.py" \
  --machine-type n2-standard-8 \
  --disk-size 500
```

### Cost-Optimized (Spot VMs)

For fault-tolerant workloads at lower cost:

```bash
gc-batch create \
  --job-name spot-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/process.py" \
  --provisioning-model SPOT
```


## Next Steps

- Learn about [Input/Output Mounts](mounts.md) for working with data in GCS
- Explore [Local SSD Storage](local-ssd.md) for high-performance I/O
- See the full [Commands Reference](commands.md)
- Learn about [Label Management](labels.md) for organizing jobs
- Check out [Example Workflows](examples.md) for real-world usage patterns

