# Job Management System

The cloud scheduler includes a comprehensive job management system to track, monitor, and control running cloud jobs. This solves the problem of losing connection or script crashes after instance launch.

## Overview

All jobs are tracked in a local SQLite database (`cloud_jobs.db`) that persists job state, instance information, and metadata. This allows you to:

- Monitor job status even after disconnection
- Manually trigger Google Drive syncs
- Terminate specific instances
- Track costs and resource usage
- Clean up old job records

## Available Commands

### 1. List Jobs (`cloud_list.py`)

View all jobs with filtering and summary options:

```bash
# List recent jobs
python cloud_list.py

# Show detailed information
python cloud_list.py --detailed

# Filter by status
python cloud_list.py --status running

# Filter by provider
python cloud_list.py --provider AWS

# Show summary statistics
python cloud_list.py --summary

# Export as JSON
python cloud_list.py --json
```

**Example Output:**
```
========================================================================================================================
Job ID       | Status      | Provider | Instance        | Region         | Duration   | Cost    
========================================================================================================================
a1b2c3d4     | running     | AWS      | r5.4xlarge      | us-east-1      | 2h 15m     | $1.01   
e5f6g7h8     | completed   | GCP      | n2-highmem-16   | us-central1    | 1h 30m     | $0.65   
i9j0k1l2     | failed      | Azure    | Standard_E16s   | eastus         | 15m        | $0.11   
```

### 2. Check Job Status (`cloud_status.py`)

Get detailed status of a specific job:

```bash
# Basic status
python cloud_status.py <job_id>

# Detailed status with file listings
python cloud_status.py <job_id> --detailed

# Raw JSON output
python cloud_status.py <job_id> --json
```

**Example Output:**
```
================================================================================
JOB STATUS: a1b2c3d4
================================================================================
Status: RUNNING
Provider: AWS
Instance: r5.4xlarge in us-east-1
Created: 2024-01-26T10:30:00
Started: 2024-01-26T10:33:15
Estimated cost: $1.0125

INSTANCE STATUS:
----------------------------------------
State: running
Public IP: 54.123.45.67
Private IP: 10.0.1.123

INPUT FILES (S3):
----------------------------------------
Files: 5
Total size: 2,456,789 bytes

RESULTS (Google Drive):
----------------------------------------
Synced files: 8
Files:
  calculation.log
  calculation_summary.json
  results.txt
  shci.out
```

### 3. Manual Resync (`cloud_resync.py`)

Trigger Google Drive sync manually:

```bash
# Resync via SSH (default)
python cloud_resync.py <job_id>

# Check Google Drive space first
python cloud_resync.py <job_id> --check-space

# Force resync even if job appears terminated
python cloud_resync.py <job_id> --force

# Use local rclone (if output directory exists locally)
python cloud_resync.py <job_id> --method local

# Dry run to see what would be synced
python cloud_resync.py <job_id> --dry-run
```

### 4. Terminate Jobs (`cloud_terminate.py`)

Safely terminate running instances:

```bash
# Terminate with confirmation prompt
python cloud_terminate.py <job_id>

# Force termination without confirmation
python cloud_terminate.py <job_id> --force

# Skip final sync attempt
python cloud_terminate.py <job_id> --no-final-sync

# Add termination reason
python cloud_terminate.py <job_id> --reason "Cost optimization"
```

**Example Output:**
```
Job a1b2c3d4: running
Provider: AWS
Instance: r5.4xlarge in us-east-1
Instance ID: i-0123456789abcdef0
Estimated cost so far: $1.0125

Are you sure you want to terminate this job? (y/N): y

Attempting final sync before termination...
✓ Final sync completed
Terminating AWS instance...
✓ Instance termination initiated
Also cancelled spot instance request
Job a1b2c3d4 marked as terminated in database
```

## Database Schema

The job tracking database stores:

- **Job metadata**: ID, status, timestamps, configuration
- **Instance details**: Provider, type, region, IDs, IP addresses
- **Cost tracking**: Hourly rates, duration, estimated costs
- **Paths**: S3 input location, Google Drive output path
- **Custom data**: Basis sets, executables, environment variables

## Job States

Jobs progress through these states:

- **launching**: Instance creation in progress
- **launched**: Instance created successfully
- **running**: Calculation has started (set by bootstrap script)
- **completed**: Calculation finished successfully
- **failed**: Instance launch or calculation failed
- **terminated**: Manually terminated or instance stopped

## Cost Tracking

The system automatically tracks:

- Instance hourly rates from spot prices
- Job duration from creation to completion
- Real-time cost estimates for running jobs
- Total costs in job summaries

## Maintenance Commands

### Cleanup Old Jobs

Remove completed job records:

```bash
# Preview what would be deleted (dry run)
python cloud_list.py --cleanup 30 --dry-run

# Actually delete jobs older than 30 days
python cloud_list.py --cleanup 30
```

### Database Backup

The SQLite database can be backed up:

```bash
# Backup database
cp cloud_jobs.db cloud_jobs_backup_$(date +%Y%m%d).db

# Restore from backup
cp cloud_jobs_backup_20240126.db cloud_jobs.db
```

## Integration with cloud_run.py

The job management system is automatically integrated:

1. **Job Creation**: `cloud_run.py` creates job records before launching instances
2. **Status Updates**: Instance details are saved after successful launch
3. **Failure Tracking**: Failed launches are recorded with error messages
4. **Cost Association**: Spot prices are stored for cost calculations

## Troubleshooting

### Connection Issues

If SSH-based operations fail:

```bash
# Check if instance is accessible
python cloud_status.py <job_id>

# Try local resync instead
python cloud_resync.py <job_id> --method local

# Force terminate if instance is unresponsive
python cloud_terminate.py <job_id> --force --no-final-sync
```

### Database Issues

If the database becomes corrupted:

```bash
# Test database integrity
python -c "from job_manager import JobManager; jm = JobManager(); print('Database OK')"

# Recreate database (loses all job history)
rm cloud_jobs.db
python -c "from job_manager import JobManager; JobManager()"
```

### Missing Jobs

If jobs don't appear in listings:

1. Check if `cloud_jobs.db` exists in the current directory
2. Verify jobs were created with the updated `cloud_run.py`
3. Check database permissions and disk space

## Best Practices

1. **Regular Monitoring**: Check job status periodically with `cloud_list.py`
2. **Cost Awareness**: Monitor costs with `--summary` flag
3. **Cleanup**: Remove old completed jobs monthly
4. **Backup**: Backup the database before major operations
5. **Termination**: Always use `cloud_terminate.py` instead of cloud console
6. **Syncing**: Use manual resync if automatic syncing seems stalled

## Example Workflow

```bash
# 1. Submit job
python cloud_run.py my_calculation --s3-bucket my-bucket --from-spot-prices

# 2. Monitor progress
python cloud_list.py --status running

# 3. Check detailed status
python cloud_status.py a1b2c3d4 --detailed

# 4. Manual resync if needed
python cloud_resync.py a1b2c3d4

# 5. Terminate if necessary
python cloud_terminate.py a1b2c3d4

# 6. Review completed jobs
python cloud_list.py --summary
```

This job management system provides full control over your cloud computing jobs, ensuring you never lose track of running instances or incur unexpected costs.