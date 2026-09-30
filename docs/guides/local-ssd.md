# Local SSD Storage

gc-batch supports using Local SSDs for high-performance, ephemeral storage. Local SSDs provide very high IOPS and low latency, making them ideal for temporary data processing, caching, and scratch space.

!!! warning "Ephemeral Storage"
    Local SSDs are **ephemeral** - all data is lost when the VM stops or terminates. Always copy important results to persistent storage (GCS buckets) before job completion.


## When to Use Local SSDs

- **Temporary processing**: Intermediate data, scratch space
- **High I/O workloads**: Applications requiring fast random reads/writes
- **Caching**: Local cache for frequently accessed data
- **Staging**: Copy from GCS → process on SSD → write back to GCS


## Manually Attaching Local SSDs

For most machine types, you can manually attach local SSDs:

```bash
gc-batch create \
  --job-name local-ssd-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type n2-standard-4 \
  --local-ssd-size-gb 375 \
  --local-ssd-device-name local-ssd-0 \
  --local-ssd-mount-path /mnt/disks/local-ssd-0
```

**How it works:**

- A local SSD is attached to the VM with the specified size
- The local SSD is automatically formatted and mounted by Google Cloud Batch
- You can immediately use the mount path in your container - no formatting needed
- The mount path is available at the specified location


## Size Requirements

Local SSD size must be a **multiple of 375 GB**:

| Size | SSDs |
|------|------|
| 375 GB | 1 SSD |
| 750 GB | 2 SSDs |
| 1125 GB | 3 SSDs |
| ... | ... |

```bash
# Attach 750 GB (2 x 375 GB) of local SSD
gc-batch create \
  --job-name multi-ssd-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type n2-standard-8 \
  --local-ssd-size-gb 750 \
  --local-ssd-mount-path /mnt/fast-storage
```


## LSSD Machine Types

LSSD machine types (e.g., `c4-standard-8-lssd`) automatically come with local SSDs pre-attached.

**Key Features:**

- Local SSDs are automatically attached and available
- No need to specify `--local-ssd-size-gb` (it will cause an error if you do)
- The local SSD is automatically formatted and mounted
- Multiple SSDs are automatically combined into a RAID0 array for maximum performance
- Default mount point is `/mnt/local_ssd`

**Example:**

```bash
gc-batch create \
  --job-name high-io-lssd-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --machine-type c4-standard-8-lssd \
  --local-ssd-mount-path /mnt/fast-storage
```

!!! note
    LSSD machine types cannot have additional local SSDs manually attached.


## Local SSD Options

| Option | Description | Default |
|--------|-------------|---------|
| `--local-ssd-size-gb` | Size in GB (multiple of 375) | - |
| `--local-ssd-device-name` | Device name | `local-ssd-0` |
| `--local-ssd-mount-path` | Mount path in container | `/mnt/disks/{device_name}` |


## Examples

### High-Performance Data Processing

```bash
gc-batch create \
  --job-name high-io-job \
  --docker-image gcr.io/my-project/processor:latest \
  --command "python /app/process.py" \
  --machine-type n2-standard-4 \
  --local-ssd-size-gb 375 \
  --local-ssd-mount-path /mnt/fast \
  --input-bucket my-data/input \
  --output-bucket my-data/output \
  --labels "use-case=high-io"
```

### Using Local SSD as Cache

In your application code:

```python
import os
import shutil

# Mount paths
input_dir = os.environ.get("INPUT_DIR", "/mnt/input")
output_dir = os.environ.get("OUTPUT_DIR", "/mnt/output")
cache_dir = "/mnt/fast"  # Local SSD mount

# Copy input data to fast local storage
shutil.copytree(input_dir, f"{cache_dir}/input")

# Process data from fast storage
process_data(f"{cache_dir}/input", f"{cache_dir}/output")

# Copy results back to GCS-mounted output
shutil.copytree(f"{cache_dir}/output", output_dir)
```


## Best Practices

1. **Use for temporary data**: Local SSDs are perfect for intermediate processing, caching, and scratch space

2. **Copy important data**: Always copy critical results to persistent storage (GCS buckets) before job completion

3. **Check availability**: Not all machine types support local SSDs - check availability in your region

4. **Size requirements**: Local SSD size must be a multiple of 375 GB

5. **Consider LSSD machine types**: For workloads that always need local SSDs, LSSD machine types are simpler to configure


## Limitations

| Limitation | Details |
|------------|---------|
| **Ephemeral** | Data is lost when VM stops or terminates |
| **Cannot combine** | Cannot manually attach SSDs to LSSD machine types |
| **Size increments** | Must be multiples of 375 GB |
| **Regional availability** | Not all machine types available in all regions |

