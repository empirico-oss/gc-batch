# Label Management

Labels help organize and filter your jobs. gc-batch automatically adds some labels and allows you to add custom ones.


## Automatic Labels

Every job created with gc-batch automatically gets these labels:

| Label | Description | Example |
|-------|-------------|---------|
| `job-name` | The name you provided for the job | `data-analysis` |
| `created-using` | Identifies jobs created by this tool; configurable via `created_using_label` | `gc-batch` |
| `created-at` | Unix timestamp when the job was created | `1703001234` |
| `created-by` | Your username, from the first env var set in `owner_email_env_vars` (default `$USER`) | `jsmith` |

These labels allow you to:
- Filter jobs by who created them (`list-my-jobs` uses `created-by`)
- Track when jobs were created
- Identify jobs created via gc-batch vs other methods


## Custom Labels

Add your own labels for better organization:

```bash
gc-batch create \
  --job-name my-job \
  --docker-image gcr.io/my-project/my-image:latest \
  --command "python /app/main.py" \
  --labels "environment=production,team=data-science,project=user-analysis,priority=high"
```

### Common Label Patterns

**By Environment:**
```bash
--labels "environment=production"
--labels "environment=staging"
--labels "environment=development"
```

**By Team:**
```bash
--labels "team=data-science"
--labels "team=bioinformatics"
--labels "team=ml-engineering"
```

**By Project:**
```bash
--labels "project=genomics,dataset=ukbb"
--labels "project=user-analysis,sprint=2024-q1"
```

**By Priority/Cost:**
```bash
--labels "priority=high,cost-center=research"
--labels "priority=low,batch-type=nightly"
```


## Filtering by Labels

### Using --labels (Simple)

```bash
# Single label
gc-batch list-jobs --labels "team=data-science"

# Multiple labels (AND logic)
gc-batch list-jobs --labels "team=data-science,environment=production"
```

### Using --filter (Advanced)

```bash
# Single label
gc-batch list-jobs --filter 'labels.environment="production"'

# Multiple labels with AND
gc-batch list-jobs --filter 'labels.team="data-science" AND labels.environment="staging"'

# Combined with other filters
gc-batch list-jobs --filter 'labels.environment="production" AND status.state="FAILED"'
```


## Label Best Practices

### 1. Use Consistent Naming

Establish standard label keys across your team:

| Key | Purpose | Values |
|-----|---------|--------|
| `team` | Team ownership | `data-science`, `ml-ops`, `bioinformatics` |
| `environment` | Deployment stage | `production`, `staging`, `development` |
| `project` | Project identifier | `genomics`, `user-analysis` |
| `priority` | Job priority | `high`, `medium`, `low` |

### 2. Keep Values Simple

- Use lowercase
- No spaces (use hyphens instead)
- Keep values short and descriptive

```bash
# Good
--labels "team=data-science,project=user-analysis"

# Avoid
--labels "team=Data Science Team,project=User Analysis Project 2024"
```

### 3. Plan for Filtering

Think about how you'll want to group and find jobs:

- "Show me all failed production jobs" → `environment=production`
- "Show me all jobs for my team" → `team=your-team`
- "Show me all jobs for this project" → `project=project-name`

### 4. Cost Tracking

Include labels that help with billing analysis:

```bash
--labels "cost-center=research,billing-code=ABC123"
```

### 5. Security

!!! warning "Don't put sensitive information in labels"
    Labels are visible in the Google Cloud Console and API responses.
    Never include passwords, API keys, or personal data in labels.


## Example Workflows

### Team Management

```bash
# List all jobs for your team
gc-batch list-jobs --labels "team=bioinformatics"

# List running jobs for your team
gc-batch list-jobs --labels "team=bioinformatics" --status RUNNING

# List failed jobs for your team from the last week
gc-batch list-jobs --labels "team=bioinformatics" --status FAILED --since 7d
```

### Production Monitoring

```bash
# List all production jobs
gc-batch list-jobs --labels "environment=production"

# List failed production jobs
gc-batch list-jobs --labels "environment=production" --status FAILED

# List production jobs for a specific project
gc-batch list-jobs --labels "environment=production,project=genomics"
```

### Project Tracking

```bash
# All jobs for a project
gc-batch list-jobs --labels "project=user-analysis"

# High-priority jobs for a project
gc-batch list-jobs --labels "project=user-analysis,priority=high"
```

