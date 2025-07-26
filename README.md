# Cloud Scheduler

Automated system for finding the cheapest cloud spot instances across AWS, GCP, and Azure, launching quantum chemistry calculations, and syncing results to Google Drive.

## Overview

This project provides a complete workflow for:
1. **Price Discovery** - Queries spot instance prices across all major cloud providers
2. **Instance Selection** - Finds the cheapest instance meeting your hardware requirements
3. **Automated Deployment** - Launches instances with pre-configured bootstrap scripts
4. **Calculation Execution** - Runs quantum chemistry calculations (SHCI/PySCF)
5. **Result Syncing** - Automatically syncs results to Google Drive during execution
6. **Cost Optimization** - Auto-terminates instances after completion

## Features

- Multi-cloud support (AWS, GCP, Azure)
- Real-time spot price comparison
- Automated instance provisioning
- Configurable hardware requirements (vCPU, RAM)
- Periodic result backup to Google Drive
- Self-terminating instances to minimize costs
- Support for custom SHCI repositories
- Robust error handling and logging

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure cloud credentials:
```bash
aws configure
gcloud auth login
az login
```

3. Find cheapest instances:
```bash
python find_cheapest_instance.py
```

4. Launch the cheapest instance:
```bash
python launch_job.py --from-file spot_prices.json --index 0
```

## Project Structure

```
cloud-scheduler/
├── find_cheapest_instance.py  # Spot price discovery across clouds
├── launch_job.py              # Instance launcher with provider abstraction
├── bootstrap.sh               # Instance initialization script
├── run_calculation.py         # Quantum chemistry calculation runner
├── requirements.txt           # Python dependencies
├── config.example.json        # Example configuration file
├── SETUP.md                   # Detailed setup instructions
└── README.md                  # This file
```

## Hardware Requirements

Default configuration searches for instances with:
- **vCPUs**: 16-32 cores
- **RAM**: 64-256 GB
- **Storage**: 100 GB SSD

These can be modified in `find_cheapest_instance.py`.

## Supported Instance Types

### AWS
- Memory optimized: r5, r5a, r6i, r7i series
- General purpose: m5, m5a, m6i series

### GCP
- Memory optimized: n2-highmem, n2d-highmem
- Standard: n2-standard, n2d-standard

### Azure
- Memory optimized: E_v5 series
- General purpose: D_v5 series

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
gdrive:shci_project/results_YYYY-MM-DD_HH-MM-SS/
├── calculation.log
├── calculation_summary.json
├── results.txt
├── FCIDUMP
└── shci.out
```

## Monitoring

- Real-time logs in calculation.log
- Progress synced every 5 minutes
- Instance status in launch_result.json
- Completion marker file when done

## Troubleshooting

See [SETUP.md](SETUP.md) for detailed setup instructions and common issues.

## License

MIT License - see LICENSE file for details
