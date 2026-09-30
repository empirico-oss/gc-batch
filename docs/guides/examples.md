# Example Workflows

Real-world examples of using gc-batch for common scenarios.

The examples below use the CLI; [the same workflows from
Python](#the-same-workflows-from-python) at the end of this page show the library
equivalents. See the [Python API guide](python-api.md) for the full library surface.


## Data Science Workflow

A typical workflow for running a data analysis job:

### 1. Create the Job

```bash
gc-batch create \
  --job-name data-analysis-001 \
  --docker-image gcr.io/my-project/data-science:latest \
  --command "python /app/analyze.py" \
  --args "--input /mnt/input/data.csv --output /mnt/output/results/" \
  --input-bucket my-bucket/datasets \
  --output-bucket my-bucket/results \
  --labels "team=data-science,project=user-analysis,priority=high" \
  --machine-type n2-standard-8 \
  --boot-disk-size 100
```

### 2. Monitor the Job

```bash
# Check status
gc-batch status --job-name data-analysis-001-1234567890

# Watch for completion (run periodically)
gc-batch list-my-jobs --status RUNNING
```

### 3. Check Logs

```bash
# View logs in console
gc-batch logs print --job-name data-analysis-001-1234567890

# Or open in Cloud Console for better viewing
gc-batch logs url --job-name data-analysis-001-1234567890
```

### 4. Retrieve Results

Your results will be in the output bucket: `gs://my-bucket/results/`


## Production Monitoring

Commands for monitoring production batch jobs:

### List All Production Jobs

```bash
gc-batch list-jobs --labels "environment=production"
```

### Find Running Production Jobs

```bash
gc-batch list-jobs --labels "environment=production" --status RUNNING
```

### Find Failed Production Jobs

```bash
# Failed in the last day
gc-batch list-jobs --labels "environment=production" --status FAILED --since 1d

# Failed in the last week
gc-batch list-jobs --labels "environment=production" --status FAILED --since 7d
```

### Debug a Failed Job

```bash
# Get status with error details
gc-batch status --job-name production-job-1234567890 --full

# View error logs
gc-batch logs url --job-name production-job-1234567890 --severity ERROR
```


## Team Management

Commands for managing jobs across a team:

### List All Team Jobs

```bash
gc-batch list-jobs --labels "team=bioinformatics"
```

### List Your Own Jobs

```bash
gc-batch list-my-jobs --since 1d
```

### List Failed Jobs for Your Team

```bash
gc-batch list-jobs --labels "team=bioinformatics" --status FAILED --since 7d
```

### List Running Jobs for Your Team

```bash
gc-batch list-jobs --labels "team=bioinformatics" --status RUNNING
```


## High-Performance Processing

For jobs requiring fast I/O:

### Using Local SSD

```bash
gc-batch create \
  --job-name high-io-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --machine-type n2-standard-8 \
  --local-ssd-size-gb 375 \
  --local-ssd-mount-path /mnt/fast \
  --input-bucket my-bucket/large-dataset \
  --output-bucket my-bucket/processed \
  --labels "use-case=high-io,team=data-engineering"
```

### Using LSSD Machine Types

```bash
gc-batch create \
  --job-name lssd-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --machine-type c4-standard-8-lssd \
  --local-ssd-mount-path /mnt/fast \
  --labels "use-case=high-io,machine=lssd"
```


## Cost-Optimized Batch Processing

For non-urgent jobs where cost is a priority:

### Using SPOT VMs

```bash
gc-batch create \
  --job-name nightly-batch \
  --docker-image gcr.io/my-project/batch-processor:latest \
  --command "python /app/batch_process.py" \
  --provisioning-model SPOT \
  --machine-type e2-standard-4 \
  --input-bucket my-bucket/daily-data \
  --output-bucket my-bucket/daily-results \
  --labels "cost-optimization=spot,schedule=nightly"
```


## ML Training Pipeline

Example for machine learning training:

### Training Job

```bash
gc-batch create \
  --job-name ml-training-v1 \
  --docker-image gcr.io/my-project/ml-trainer:latest \
  --command "python /app/train.py" \
  --args "--epochs 100 --batch-size 32 --model-name resnet50" \
  --input-bucket my-ml-bucket/training-data \
  --output-bucket my-ml-bucket/models/v1 \
  --machine-type n2-standard-16 \
  --boot-disk-size 200 \
  --labels "team=ml,project=image-classification,version=v1"
```

### Check Training Progress

```bash
# View training logs
gc-batch logs print --job-name ml-training-v1-1234567890

# Or in Cloud Console
gc-batch logs url --job-name ml-training-v1-1234567890
```


## Genomics Processing

Example for bioinformatics workloads:

### Genome Sequencing Job

```bash
gc-batch create \
  --job-name genome-sequencing-sample001 \
  --docker-image gcr.io/my-project/sequencing:latest \
  --command "python /app/sequence.py" \
  --args "--sample-id SAMPLE_001 --reference hg38" \
  --input-bucket my-genomics-bucket/raw-samples/SAMPLE_001 \
  --output-bucket my-genomics-bucket/processed/SAMPLE_001 \
  --machine-type n2-highmem-8 \
  --boot-disk-size 500 \
  --local-ssd-size-gb 375 \
  --local-ssd-mount-path /mnt/scratch \
  --labels "team=bioinformatics,project=genomics,sample=SAMPLE_001"
```


## Batch Job with Custom Environment

Passing configuration via environment variables:

```bash
gc-batch create \
  --job-name configured-job \
  --docker-image gcr.io/my-project/my-app:latest \
  --command "python /app/main.py" \
  --env "DATABASE_URL=postgres://...,LOG_LEVEL=DEBUG,MAX_WORKERS=4" \
  --input-bucket my-bucket/config \
  --output-bucket my-bucket/output \
  --labels "environment=staging,config=custom"
```


## The Same Workflows From Python

Anything above can be done from a script or notebook instead. All of these share
one client:

```python
from gc_batch import BatchClientConfig, BatchJobConfig, GCBatchClient, JobRequest

client = GCBatchClient(BatchClientConfig(project_id="my-project", location="us-central1"))
```

### Data Science Workflow

Submit, wait, then act on the outcome — the part that is awkward to script around
the CLI:

```python
import time

from gc_batch.utils import is_job_finished

job = client.create_job(
    JobRequest(
        job_name="data-analysis-001",
        docker_image="gcr.io/my-project/data-science:latest",
        command="python /app/analyze.py",
        args="--input /mnt/input/data.csv --output /mnt/output/results/",
        config=BatchJobConfig(
            machine_type="n2-standard-8",
            boot_disk_type="pd-balanced",
            boot_disk_size=100,
            input_bucket="my-bucket/datasets",
            output_bucket="my-bucket/results",
        ),
        labels={"team": "data-science", "project": "user-analysis", "priority": "high"},
    )
)

short_name = job.name.split("/")[-1]
while not is_job_finished(job := client.get_job(short_name)):
    time.sleep(30)

if job.status.state.name == "SUCCEEDED":
    print("Results in gs://my-bucket/results/")
else:
    print(client.get_failure_message(job))
    client.batch_logging.print_logs_for_job(job, severity="ERROR")
```

### Production Monitoring

```python
from datetime import datetime, timedelta, timezone

running = client.list_jobs(labels={"environment": "production"}, status="RUNNING")
print(f"{len(running)} production jobs running")

failures = client.list_jobs(
    labels={"environment": "production"},
    status="FAILED",
    since_time=datetime.now(timezone.utc) - timedelta(days=1),
)
for job in failures:
    print(f"\n{job.name.split('/')[-1]}")
    print(client.get_failure_message(job))
    print(client.get_cloud_logging_url(job, severity="ERROR"))
```

This is the natural hook for an alerting job: run it on a schedule and post the
failure summaries and log URLs wherever your team watches.

### Cost-Optimized Batch Processing

```python
job = client.create_job(
    JobRequest(
        job_name="nightly-batch",
        docker_image="gcr.io/my-project/batch-processor:latest",
        command="python /app/batch_process.py",
        config=BatchJobConfig(
            machine_type="e2-standard-4",
            boot_disk_type="pd-balanced",
            provisioning_model="SPOT",
            input_bucket="my-bucket/daily-data",
            output_bucket="my-bucket/daily-results",
        ),
        labels={"cost-optimization": "spot", "schedule": "nightly"},
    )
)
```

### ML Hyperparameter Sweep

Submitting a job per configuration is where the library pulls ahead of the CLI —
the sweep is a loop, not a generated shell script:

```python
GRID = [
    {"epochs": 50, "batch_size": 32},
    {"epochs": 50, "batch_size": 64},
    {"epochs": 100, "batch_size": 32},
    {"epochs": 100, "batch_size": 64},
]

config = BatchJobConfig(
    machine_type="n2-standard-16",
    boot_disk_type="pd-balanced",
    boot_disk_size=200,
    input_bucket="my-ml-bucket/training-data",
    output_bucket="my-ml-bucket/models/sweep",
)

for index, params in enumerate(GRID):
    client.create_job(
        JobRequest(
            job_name=f"ml-training-sweep-{index}",
            docker_image="gcr.io/my-project/ml-trainer:latest",
            command="python /app/train.py",
            args=(
                f"--epochs {params['epochs']} "
                f"--batch-size {params['batch_size']} "
                f"--model-name resnet50"
            ),
            config=config,
            labels={
                "team": "ml",
                "project": "image-classification",
                "sweep": "resnet50-v1",
                "epochs": str(params["epochs"]),
                "batch-size": str(params["batch_size"]),
            },
        )
    )
```

Then watch the whole sweep with a single call, since every job carries the same
`sweep` label:

```python
sweep_jobs = client.list_jobs(labels={"sweep": "resnet50-v1"})
for job in sweep_jobs:
    print(job.name.split("/")[-1], job.status.state.name)
```

