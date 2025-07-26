# Cloud Scheduler

Automated system for finding the cheapest cloud spot instances across AWS, GCP, and Azure, launching computational workloads, and syncing results to Google Drive. Now includes comprehensive **cost tracking and budgeting** capabilities.

## Overview

This project provides a complete workflow for:
1. **Dynamic Instance Discovery** - 🆕 Real-time API queries discover ALL available instance types
2. **Price Discovery** - Queries spot instance prices across all major cloud providers
3. **Instance Selection** - Finds the cheapest instance meeting your hardware requirements
4. **Secure Authentication** - 🆕 Proper credential validation for all cloud providers
5. **Budget Validation** - Prevents job launches that exceed cost limits
6. **File Staging** - Uploads job files to S3 for reliable transfer to instances
7. **Automated Deployment** - Launches instances with pre-configured bootstrap scripts
8. **Computation Execution** - Runs computational workloads with customizable scripts
9. **Result Syncing** - Automatically syncs results to Google Drive with configurable exclusions
10. **Cost Tracking** - Retrieves actual costs from cloud provider billing APIs
11. **Cost Analysis** - Comprehensive reporting on spending patterns and budget performance

## Features

- **🆕 Dynamic Instance Discovery** - Real-time API queries for latest instance types
- **🆕 Enhanced Security** - Proper authentication and credential validation
- **🆕 Rate Limiting** - Exponential backoff prevents API quota issues
- Multi-cloud support (AWS, GCP, Azure)
- Real-time spot price comparison with interactive selection
- **Cost tracking and budgeting** with billing API integration
- **Budget validation** to prevent expensive job launches  
- **Comprehensive cost reporting** and analysis tools
- S3 staging for reliable file transfer
- **Docker containerization** for reproducible environments
- Automated instance provisioning
- Configurable hardware requirements (vCPU, RAM)
- Periodic result backup to Google Drive
- Configurable file exclusions from syncs to save bandwidth/storage
- Self-terminating instances to minimize costs
- Support for custom software repositories and environments
- Robust error handling and logging

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure cloud credentials and S3:
```bash
# AWS setup
aws configure
aws s3 mb s3://my-compute-jobs  # Create S3 bucket

# GCP setup (required for dynamic discovery)
gcloud auth login
gcloud auth application-default login  # For API access

# Azure setup (enhanced with new SDK)
az login  # For DefaultAzureCredential
```

3. Find cheapest instances with dynamic discovery:
```bash
python find_cheapest_instance.py
```

**🆕 What's New:**
- **Dynamic Discovery**: Automatically queries ALL available instance types from cloud APIs
- **Credential Validation**: Verifies authentication before API calls
- **Rate Limiting**: Built-in throttling prevents quota issues
- **Enhanced Error Handling**: Helpful messages for credential and API issues

This displays instances with both hourly and per-core pricing, then presents an interactive menu:

**Option 1**: Cheapest per-core instance  
**Option 2**: Cheapest overall instance (if different from option 1)  
**Option 3**: Higher memory alternative (if available and cost-effective)  
**Option 4**: Abort

Your selection is saved as index 0 in `spot_prices.json` for easy use with `cloud_run.py --from-spot-prices`.

For non-interactive mode:
```bash
python find_cheapest_instance.py --no-interactive --min-vcpu 16 --max-vcpu 32
```

4. Submit a job:
```bash
# Traditional deployment
python cloud_run.py ./my_job_files --s3-bucket my-compute-jobs --from-spot-prices

# Docker deployment (recommended)
python cloud_run.py ./my_job_files --s3-bucket my-compute-jobs --from-spot-prices --docker
```

## Project Structure

```
cloud-scheduler/
├── find_cheapest_instance.py  # Spot price discovery with interactive selection
├── cloud_run.py               # Main job submission interface with S3 staging
├── launch_job.py              # Instance launcher with provider abstraction
├── job_manager.py             # Job tracking and cost database management
├── cost_tracker.py            # Cloud provider billing API integration
├── cloud_cost_report.py       # Cost reporting and analysis tools
├── update_job_completion.py   # Job completion and cost tracking workflow
├── bootstrap.sh               # Instance initialization script
├── run_calculation.py         # Example computational calculation runner
├── requirements.txt           # Python dependencies
├── config.example.json        # Example configuration file
├── config_profiles/           # Pre-configured calculation profiles
├── container_scripts/         # Docker container scripts
├── Dockerfile                 # Container image definition
├── docker-compose.yml         # Local development setup
├── bootstrap-docker.sh        # Docker-based bootstrap script
├── SETUP.md                   # Detailed setup instructions
├── CONFIGURATION.md           # Configuration guide and profiles
├── DOCKER.md                  # Docker containerization guide
├── TROUBLESHOOTING.md         # 🆕 Comprehensive troubleshooting guide
├── COST_TRACKING.md           # Cost tracking and budgeting guide
├── example_usage.md           # Complete usage walkthrough
└── README.md                  # This file
```

## Hardware Requirements

Configure hardware requirements in `config.json` or via command-line arguments:

**Default requirements:**
- **vCPUs**: 16-32 cores
- **RAM**: 64-256 GB
- **Storage**: 100 GB SSD

**Configuration methods:**
1. **Config file** (`config.json`):
   ```json
   {
     "hardware": {
       "min_vcpu": 16,
       "max_vcpu": 32,
       "min_ram_gb": 64,
       "max_ram_gb": 256
     }
   }
   ```

2. **Command-line arguments**:
   ```bash
   python find_cheapest_instance.py --min-vcpu 8 --max-vcpu 16 --min-ram 32 --max-ram 128
   python cloud_run.py my_job --min-vcpu 32 --max-vcpu 64 --min-ram 256
   ```

3. **Configuration profiles** (see `config_profiles/` directory):
   - `small_calculation.json` - 4-16 vCPUs, 16-64GB RAM
   - `large_calculation.json` - 32-128 vCPUs, 256-1024GB RAM  
   - `memory_intensive.json` - 16-64 vCPUs, 128-512GB RAM

## Cost Tracking and Budgeting

The system now includes comprehensive cost tracking that integrates with cloud provider billing APIs:

### Budget Validation
```bash
# Set budget limit to prevent expensive job launches
python cloud_run.py my_job --s3-bucket my-bucket --budget 10.00 --estimated-runtime 3.0
```

### Cost Reporting
```bash
# View detailed cost summary for a job
python cloud_cost_report.py job <job-id>

# Analyze cost trends over time
python cloud_cost_report.py trends --days 30

# Compare costs across cloud providers
python cloud_cost_report.py compare
```

### Automatic Cost Retrieval
After job completion, actual costs are automatically retrieved from:
- **AWS Cost Explorer API** - Detailed spot instance costs
- **GCP Cloud Billing API** - Preemptible instance costs  
- **Azure Cost Management API** - Spot VM costs

**See [COST_TRACKING.md](COST_TRACKING.md) for detailed documentation.**

## Supported Instance Types

The system **dynamically discovers all available instance types** from each cloud provider's API that match your hardware requirements, rather than being limited to a predefined list.

### Dynamic Instance Discovery

**AWS**: Uses EC2 `describe_instance_types()` API to discover all available instance types
- Automatically finds all current and new instance types (r5, r6i, r7i, m5, m6i, c5, c6i, x1e, z1d, etc.)
- Includes latest generation instances as they become available
- Filters based on your vCPU and RAM requirements

**GCP**: Uses Compute Engine `machineTypes.list()` API to discover machine types
- Discovers all machine families (n1, n2, n2d, e2, t2d, c2, etc.)
- Includes both predefined and custom machine types
- Automatically discovers new machine types as Google releases them

**Azure**: Uses Compute SKUs API and Retail Prices API for VM discovery
- Discovers all VM series (D, E, F, H, L, M, N, etc.)
- Includes latest VM generations (v3, v4, v5, etc.)
- Automatically includes new VM sizes as they're released

### Instance Type Filtering

The system automatically filters discovered instances based on your requirements:
- **vCPU range**: Only includes instances within your min/max CPU range
- **Memory range**: Only includes instances within your min/max RAM range  
- **Spot availability**: Only queries pricing for instances available as spot/preemptible
- **Regional availability**: Checks availability across all regions

This approach ensures you always have access to the latest and most cost-effective instances without needing code updates.

## Configuration

Create a `config.json` file based on `config.example.json`:

```json
{
  "aws": {
    "key_name": "your-keypair",
    "security_group": "cloud-scheduler-sg",
    "iam_role": "cloud-scheduler-role"
  },
  "gcp": {
    "project_id": "your-project-id"
  },
  "azure": {
    "subscription_id": "your-subscription-id"
  }
}
```

## Security

- Credentials are stored in cloud-native secret managers
- Instances use IAM roles/service accounts instead of keys
- All instances are auto-terminated after job completion
- Results are encrypted in transit to Google Drive

## Cost Optimization

- Automatically finds cheapest spot instances
- Uses preemptible/spot pricing (60-90% savings)
- Auto-terminates on completion
- Configurable price caps per provider

## Output

Results are automatically synced to Google Drive:
```
gdrive:compute_project/results_YYYY-MM-DD_HH-MM-SS/
├── calculation.log
├── results_summary.json
├── results.txt
├── output.out
└── (large files excluded from sync)
```

Note: Large computational files are automatically excluded from Google Drive syncs to save bandwidth and storage space. They remain available on the S3 bucket if needed.

## Monitoring

- Real-time logs in calculation.log
- Progress synced every 5 minutes
- Instance status in launch_result.json
- Completion marker file when done

## Troubleshooting

See [SETUP.md](SETUP.md) for detailed setup instructions and common issues.

## License

MIT License - see LICENSE file for details
