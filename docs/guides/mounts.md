# Input/Output Mounts

gc-batch supports mounting Google Cloud Storage buckets as input and output directories in your jobs, making it easy to work with data stored in GCS.


## Input Mounts

Mount a GCS bucket folder as an input directory:

```bash
gc-batch create \
  --job-name data-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --input-bucket my-bucket/input-data \
  --input-dir /mnt/input
```

**How it works:**

- The GCS path `my-bucket/input-data` is mounted at `/mnt/input` in your container
- Your application can read files from `/mnt/input/` as if they were local files
- The mount is writable, not read-only: gcsfuse mounts it read-write, so writes
  under `/mnt/input/` modify the real objects in `my-bucket/input-data`. Treat it
  as read-only by convention — the input directory is meant for reading, not
  writing — rather than relying on the mount to enforce that for you


## Output Mounts

Mount a GCS bucket folder as a writable output directory:

```bash
gc-batch create \
  --job-name data-analysis \
  --docker-image gcr.io/my-project/analyzer:latest \
  --command "python /app/analyze.py" \
  --output-bucket my-bucket/results \
  --output-dir /mnt/output
```

**How it works:**

- The GCS path `my-bucket/results` is mounted at `/mnt/output` in your container
- Your application can write files to `/mnt/output/` and they'll be uploaded to GCS
- The mount is read-write for output generation


## Combined Input and Output

Use both input and output mounts together:

```bash
gc-batch create \
  --job-name data-pipeline \
  --docker-image gcr.io/my-project/pipeline:latest \
  --command "python /app/run_pipeline.py" \
  --input-bucket my-bucket/raw-data \
  --input-dir /mnt/input \
  --output-bucket my-bucket/processed-data \
  --output-dir /mnt/output
```


## Requester-Pays Buckets

For buckets with "Requester Pays" enabled, specify a billing project:

```bash
gc-batch create \
  --job-name data-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --input-bucket external-bucket/data \
  --input-billing-project my-billing-project \
  --input-dir /mnt/input
```

**When to use billing project:**

- When the input bucket has "Requester Pays" enabled
- When you need to control which project is billed for access charges
- When accessing buckets owned by other projects


## Sending Logs to a GCS Bucket

By default, Batch jobs send their logs to Cloud Logging. If Cloud Logging is not accessible (for example, due to a platform issue), you can instead write logs directly to a GCS bucket:

```bash
gc-batch create \
  --job-name data-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --logs-bucket my-bucket/batch-logs
```

**How it works:**

- The logs bucket is mounted on the job VM and the Batch agent writes logs directly to it.
- Each job gets its own subfolder: logs land under `<logs-bucket-path>/<full-job-name>/`, e.g. `my-bucket/batch-logs/data-processing-1234567890/`.
- Batch writes three objects per task — `stdout-…log`, `stderr-…log`, and `output-…log` (the superset, which also contains the Batch agent's own lines).
- `gc-batch logs print` and `gc-batch logs download` read these objects for you: they detect that the job writes to GCS and read the bucket instead of querying Cloud Logging, so no Cloud Logging access is required.
- Lines appear in the order the Batch agent received them, which is not always the order your program wrote them. Standard output is block-buffered when it is not a terminal, so a script that writes to stdout and then to stderr often has its stderr recorded *first* — stderr is unbuffered and arrives immediately, while the buffered stdout is flushed when the process exits. Call `sys.stdout.flush()` (or run Python with `-u`) if you need the two streams to interleave as written.

```bash
# Reads straight from the logs bucket for a job created with --logs-bucket
gc-batch logs print --job-name data-processing-1234567890
gc-batch logs download --job-name data-processing-1234567890 --download-dir ./logs
```

!!! warning "Single log destination"
    Google Cloud Batch supports only one log destination per job. When `--logs-bucket` is set, logs go to the bucket **instead of** Cloud Logging. `gc-batch logs filter` and `gc-batch logs url` still produce Cloud Logging queries, which will match nothing for such a job; both commands now say so.

For requester-pays logs buckets, pass a billing project:

```bash
gc-batch create \
  --job-name data-processing \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --logs-bucket external-bucket/batch-logs \
  --logs-billing-project my-billing-project
```


## Environment Variables

When you specify input and output mounts, the CLI automatically sets these environment variables in your container:

| Variable | Description |
|----------|-------------|
| `INPUT_DIR` | The input mount path (e.g., `/mnt/input`) |
| `OUTPUT_DIR` | The output mount path (e.g., `/mnt/output`) |

Use these in your application:

```python
import os

input_dir = os.environ.get("INPUT_DIR", "/mnt/input")
output_dir = os.environ.get("OUTPUT_DIR", "/mnt/output")

# Process files from input directory
for filename in os.listdir(input_dir):
    input_path = os.path.join(input_dir, filename)
    # Process the file...

    # Write results to output directory
    output_path = os.path.join(output_dir, f"processed_{filename}")
    # Save results...
```


## Mount Options Summary

### Input Mount Options

| Option | Description | Default |
|--------|-------------|---------|
| `--input-bucket` | GCS bucket path (e.g., `my-bucket/data`) | - |
| `--input-dir` | Mount point in container | `/mnt/input` |
| `--input-billing-project` | Billing project for requester-pays | - |

### Output Mount Options

| Option | Description | Default |
|--------|-------------|---------|
| `--output-bucket` | GCS bucket path (e.g., `my-bucket/results`) | - |
| `--output-dir` | Mount point in container | `/mnt/output` |

### Log Output Options

| Option | Description | Default |
|--------|-------------|---------|
| `--logs-bucket` | GCS bucket path to write job logs to (replaces Cloud Logging) | - |
| `--logs-billing-project` | Billing project for requester-pays logs bucket | - |


## Examples

### Data Science Workflow

```bash
gc-batch create \
  --job-name ml-training \
  --docker-image gcr.io/my-project/ml-trainer:latest \
  --command "python /app/train_model.py" \
  --input-bucket my-ml-bucket/datasets \
  --output-bucket my-ml-bucket/models \
  --labels "team=ml,project=training"
```

### File Processing Pipeline

```bash
gc-batch create \
  --job-name image-processing \
  --docker-image gcr.io/my-project/image-processor:latest \
  --command "python /app/process_images.py" \
  --input-bucket my-images/raw \
  --input-dir /data/input \
  --output-bucket my-images/processed \
  --output-dir /data/output \
  --machine-type n2-standard-4
```


## Best Practices

1. **Don't mount entire buckets**: Mount specific subfolders to limit scope and improve performance
   ```bash
   # Good: specific subfolder
   --input-bucket my-bucket/project-x/input-data
   
   # Avoid: entire bucket
   --input-bucket my-bucket
   ```

2. **Use descriptive bucket paths**: Organize your data with clear folder structures

3. **For lots of read operations**: Consider copying data to local SSD for better performance

4. **For lots of write operations**: Stage output on local SSD, then copy to output at end

5. **Use environment variables**: Leverage `INPUT_DIR` and `OUTPUT_DIR` for flexibility in your code

