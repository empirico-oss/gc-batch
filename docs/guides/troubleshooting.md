# Troubleshooting

Common issues and solutions when using gc-batch.


## Common Issues


### Command Not Found

**Symptom:** `gc-batch: command not found` after installing.

**Cause:** The install location is not on your `PATH`.

**Solution:** Add the uv tool directory to your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Or run it through uv without installing:

```bash
uv run gc-batch --help
```


### Wrong Docker Image Platform

**Symptom:** Job fails with error in logs:
```
The requested image's platform (linux/arm64/v8) does not match the detected 
host platform (linux/amd64/v4) and no specific platform was requested
```

**Cause:** Your Docker image was built for ARM architecture (common on Apple Silicon Macs) but Google Cloud Batch runs on AMD64/x86 VMs.

**Solution:** Rebuild your Docker image for the correct platform:

```bash
docker build --platform linux/amd64 -t your-image:tag .
```

Or use buildx for multi-platform builds:

```bash
docker buildx build --platform linux/amd64 -t your-image:tag --push .
```


### Job Stuck in QUEUED State

**Symptom:** Job stays in `QUEUED` status for a long time.

**Possible Causes:**

1. **Insufficient quota** - Check your GCP quota for the region and machine type
2. **Resource unavailability** - The requested machine type may not be available in the zone
3. **SPOT VM shortage** - If using `--provisioning-model SPOT`, capacity may be limited

**Solutions:**

- Try a different machine type
- Try a different region
- Use `STANDARD` provisioning instead of `SPOT`
- Check GCP Console for quota issues


### Authentication Errors

**Symptom:** Commands fail with authentication errors.

**Solution:** Re-authenticate with Google Cloud:

```bash
# Login to Google Cloud
gcloud auth login

# Set application default credentials
gcloud auth application-default login

# Verify your account
gcloud auth list
gcloud config get-value account
```


### Permission Denied Errors

**Symptom:** Job creation fails with permission errors.

**Possible Causes:**

1. Missing Batch API permissions
2. Missing Storage permissions for GCS buckets
3. Service account doesn't have required roles

**Solutions:**

```bash
# Enable the Batch API
gcloud services enable batch.googleapis.com

# Check your permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID
```

Required roles:
- `roles/batch.jobsEditor` - Create and manage Batch jobs
- `roles/storage.objectViewer` - Read from GCS buckets
- `roles/storage.objectCreator` - Write to GCS buckets


### GCS Mount Issues

**Symptom:** Job can't read/write to mounted GCS buckets.

**Possible Causes:**

1. Bucket doesn't exist
2. Incorrect bucket path
3. Permission issues
4. Requester-pays bucket without billing project

**Solutions:**

```bash
# Verify bucket exists and you have access
gsutil ls gs://your-bucket/path/

# For requester-pays buckets, specify billing project
gc-batch create \
  --job-name my-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --input-bucket requester-pays-bucket/data \
  --input-billing-project your-billing-project
```

!!! tip "Don't mount entire buckets"
    Mount specific subfolders, not entire buckets:
    
    ```bash
    # Good
    --input-bucket my-bucket/project/input-data
    
    # Avoid
    --input-bucket my-bucket
    ```


### Local SSD Errors

**Symptom:** Job fails when using local SSD options.

**Possible Causes:**

1. Invalid SSD size (must be multiple of 375 GB)
2. LSSD machine type with `--local-ssd-size-gb` specified
3. Machine type doesn't support local SSD

**Solutions:**

```bash
# Ensure size is multiple of 375
--local-ssd-size-gb 375   # ✓
--local-ssd-size-gb 750   # ✓
--local-ssd-size-gb 400   # ✗ Error!

# For LSSD machine types, DON'T specify size
gc-batch create \
  --job-name lssd-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type c4-standard-8-lssd \
  --local-ssd-mount-path /mnt/fast  # Only specify mount path
```


### Job Failed - How to Debug

**Steps to debug a failed job:**

1. **Check status with error details:**
   ```bash
   gc-batch status --job-name your-job-name --full
   ```

2. **View logs:**
   ```bash
   # Print to console
   gc-batch logs print --job-name your-job-name
   
   # View in Cloud Console (more features)
   gc-batch logs url --job-name your-job-name
   
   # View only errors
   gc-batch logs url --job-name your-job-name --severity ERROR
   ```

3. **Download logs for analysis:**
   ```bash
   gc-batch logs download --job-name your-job-name --download-dir ./debug-logs
   ```

If those commands report no logs, the next two sections cover the two reasons why.


### Job Failed but There Are No Logs At All

**Symptom:** the job is `FAILED`, `status` says only something like
`Task state is updated from RUNNING to FAILED … with exit code 1`, and
`gc-batch logs print` finds nothing — for a Cloud Logging job *and* for a
`--logs-bucket` job.

**Cause:** the container never started, so it produced no output to collect. The
usual reason is an image that could not be pulled: a bad tag, a registry the job's
network cannot reach, or missing permission on the image. When this happens Batch
does not write any log objects to a `--logs-bucket` path either, because the failure
precedes the container.

**Batch does not report the reason.** The image name appears nowhere in the failure
text, and the job resource contains no "manifest unknown", "not found", or "pull"
message — the only failure detail is an exit code. `gc-batch status` therefore adds a
*clearly labelled inference* when a `FAILED` job produced no log entries at all,
naming the image so you can check it. That is a deduction from the absence of logs,
not something Batch told us.

**What to check:**

```bash
# Confirm the exact image reference the job was given
gc-batch status --job-name your-job-name --full | grep -i imageUri

# Confirm that reference exists and you can pull it
gcloud container images describe IMAGE_URI
```

Then confirm the job's network can reach that registry at all. A pull that cannot
reach its registry fails in exactly the same way as a bad tag, so the two are worth
separating: if a job using a *known-good* image from the same registry succeeds, the
registry is reachable and the problem is the reference.

Jobs created with `--job-profile all-of-us` run on VMs with no external IP address,
but that does not restrict you to Google registries: both `gcr.io` and Docker Hub
(`docker.io/library/debian:stable-slim`) have been confirmed to pull successfully
from such a VM in the All of Us Researcher Workbench. If a pull fails there, suspect
the image reference before the network.

!!! warning "Also check the entrypoint"
    `gc-batch` runs your command through `/bin/bash -c`. An image without
    `/bin/bash` — `busybox` and most `alpine`-based images — fails at container start
    for the same reason and looks identical in `status`. Use a Debian- or
    Ubuntu-based image, or one that ships bash.


### "Permission denied for all log views"

**Symptom:** `gc-batch logs print` exits non-zero with
`403 Permission denied for all log views`, and the Cloud Console logs page is empty
too.

**Cause:** the identity running `gc-batch` cannot read Cloud Logging in that project.
This is the normal state in restricted environments — notably the All of Us
Researcher Workbench, where the workspace pet service account has no log view
access at all — and no filter or time-range change will help.

**Solution:** have Batch write logs to a GCS bucket instead, which needs no Cloud
Logging access. This is a *creation-time* choice, so it cannot be applied to jobs
that have already run:

```bash
gc-batch create \
  --job-name my-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --logs-bucket my-bucket/batch-logs
```

`gc-batch logs print` and `logs download` detect such jobs and read the bucket
automatically. See [Input/Output Mounts](mounts.md) for the object layout, and note
that `logs filter` and `logs url` still produce Cloud Logging queries, which will
match nothing for these jobs.

!!! tip "Multi-task jobs write one set of objects per task"
    Objects are named `{stream}-{job-uid}-group{GROUP}-{TASK}.log`, so a job with
    `--task-count 2` writes six: `stdout-`, `stderr-`, and `output-` for
    `group0-0` and again for `group0-1`. `output-` is the superset and also contains
    the Batch agent's own lines. If you are looking for one task's output, filter by
    its `group{GROUP}-{TASK}` suffix.


## Getting Help

### Command Help

```bash
# General help
gc-batch --help

# Command-specific help
gc-batch create --help
gc-batch list-jobs --help
gc-batch status --help
gc-batch logs --help
gc-batch cancel --help
```

### Check Version

```bash
gc-batch --version
```

### Useful GCloud Commands

```bash
# Check Batch API status
gcloud services list --enabled | grep batch

# List Batch jobs directly via gcloud
gcloud batch jobs list --location=us-central1

# Describe a job
gcloud batch jobs describe JOB_NAME --location=us-central1
```

