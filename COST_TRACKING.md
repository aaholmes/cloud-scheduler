# Cost Tracking and Budgeting

The cloud scheduler now includes comprehensive cost tracking and budgeting capabilities that integrate with cloud provider billing APIs to provide actual cost data and budget controls.

## Overview

The cost tracking system provides:

- **Actual cost retrieval** from cloud provider billing APIs (AWS Cost Explorer, GCP Cloud Billing, Azure Cost Management)
- **Budget validation** to prevent expensive jobs from launching
- **Comprehensive cost reporting** with trends, provider comparisons, and budget analysis
- **Automatic cost tracking** integrated with the job completion workflow

## Quick Start

### Setting a Budget

Prevent jobs from launching if estimated cost exceeds your budget:

```bash
# Launch job with $10 budget limit for 3-hour estimated runtime
python cloud_run.py my_job_dir --s3-bucket my-bucket --budget 10.00 --estimated-runtime 3.0
```

### Viewing Job Costs

Get detailed cost information for completed jobs:

```bash
# View cost summary for a specific job
python cloud_cost_report.py job <job-id>

# View cost trends over the last 30 days
python cloud_cost_report.py trends --days 30

# Analyze budget performance
python cloud_cost_report.py budget

# Compare costs across cloud providers
python cloud_cost_report.py compare --days 30
```

### Retrieving Actual Costs

For completed jobs, retrieve actual costs from cloud provider billing APIs:

```bash
# Retrieve costs for a specific job
python cost_tracker.py --job-id <job-id>

# Batch retrieve costs for recent jobs
python cost_tracker.py --batch --max-jobs 20
```

## Features

### 1. Budget Validation

The `--budget` flag prevents job launches when estimated costs exceed your limit:

- **Pre-launch validation**: Calculates estimated cost based on instance pricing and runtime
- **Intelligent instance selection**: Automatically filters instances that fit within budget
- **Clear error messages**: Provides actionable feedback when budget is exceeded

```bash
# Example: Budget validation failure
$ python cloud_run.py my_job --s3-bucket test --budget 5.00 --estimated-runtime 10.0
ERROR: Estimated cost $8.0000 exceeds budget $5.00
ERROR: Instance: r5.4xlarge @ $0.8000/hour for 10.0 hours
ERROR: Use --estimated-runtime to adjust runtime estimate or increase --budget
```

### 2. Actual Cost Retrieval

After job completion, the system automatically retrieves actual costs from cloud provider billing APIs:

#### AWS Cost Explorer API
- Queries actual spot instance costs with resource-level granularity
- Filters by instance ID and spot usage type
- Includes cost breakdowns by usage type and billing period

#### GCP Cloud Billing API
- Framework for BigQuery billing export integration
- Fallback to pricing API for cost estimation
- Support for preemptible instance cost tracking

#### Azure Cost Management API
- Resource-level cost queries using subscription scopes
- Tag-based cost allocation and filtering
- Support for spot VM cost tracking

### 3. Cost Database Schema

The system extends the job database with cost-specific fields:

#### Enhanced Jobs Table
```sql
-- New cost-related columns in jobs table
actual_cost REAL,           -- Actual cost retrieved from billing API
budget_limit REAL,          -- User-specified budget limit
cost_retrieved_at TEXT,     -- Timestamp when cost was retrieved
spot_request_id TEXT,       -- Cloud provider spot request ID
billing_tags TEXT          -- JSON tags for cost allocation
```

#### Cost Tracking Table
```sql
-- Detailed cost breakdown table
CREATE TABLE cost_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    cost_type TEXT NOT NULL,           -- e.g., 'spot_compute', 'storage'
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    billing_period_start TEXT NOT NULL,
    billing_period_end TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    raw_data TEXT,                     -- JSON of provider-specific data
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);
```

### 4. Comprehensive Reporting

The cost reporting system provides multiple views of your cloud spending:

#### Job-Level Reports
```bash
python cloud_cost_report.py job <job-id>
```
- Detailed cost breakdown for individual jobs
- Budget vs. actual cost comparison
- Cost accuracy analysis (estimated vs. actual)
- Provider-specific cost details

#### Cost Trends
```bash
python cloud_cost_report.py trends --days 30 --provider AWS
```
- Historical cost analysis over time periods
- Provider breakdown and comparisons
- Daily cost trends and patterns
- Total and average cost metrics

#### Budget Analysis
```bash
python cloud_cost_report.py budget
```
- Budget success rate analysis
- Jobs over budget identification
- Budget utilization metrics
- Cost savings and overrun tracking

#### Provider Comparison
```bash
python cloud_cost_report.py compare --days 30
```
- Cost comparison across AWS, GCP, and Azure
- Provider reliability and success rates
- Recommendations for cost optimization

### 5. Automatic Integration

The cost tracking system automatically integrates with the existing job workflow:

1. **Job Creation**: Budget limits and cost parameters are stored in the database
2. **Budget Validation**: Pre-launch checks prevent over-budget jobs
3. **Job Execution**: Instance metadata is collected during execution
4. **Job Completion**: Automatic cost retrieval is scheduled
5. **Cost Reporting**: Historical data enables trend analysis

## Configuration

### Cloud Provider Setup

#### AWS
```json
{
  "aws": {
    "region": "us-east-1"
  }
}
```

Required IAM permissions:
- `ce:GetCostAndUsage`
- `ce:GetUsageReport`
- `ec2:DescribeSpotPriceHistory`

#### GCP
```json
{
  "gcp": {
    "project_id": "your-project-id"
  }
}
```

Required permissions:
- `cloudbilling.billingAccounts.get`
- `compute.instances.get`

#### Azure
```json
{
  "azure": {
    "subscription_id": "your-subscription-id"
  }
}
```

Required permissions:
- `Microsoft.CostManagement/query/action`
- `Microsoft.Compute/virtualMachines/read`

### Budget Configuration

Set default budget limits and runtime estimates:

```json
{
  "defaults": {
    "budget_limit": 20.00,
    "estimated_runtime": 2.0
  }
}
```

## Command Reference

### cloud_run.py Budget Options

```bash
python cloud_run.py JOB_DIR --s3-bucket BUCKET [OPTIONS]

Budget Options:
  --budget AMOUNT          Maximum budget limit in USD
  --estimated-runtime HOURS Runtime estimate for cost calculation (default: 2.0)
```

### find_cheapest_instance.py Budget Filtering

```bash
python find_cheapest_instance.py [OPTIONS]

Budget Options:
  --budget AMOUNT           Total budget limit in USD
  --max-price-per-hour RATE Maximum hourly rate in USD
  --estimated-runtime HOURS Runtime for budget calculation (default: 2.0)
```

### cost_tracker.py Cost Retrieval

```bash
python cost_tracker.py [OPTIONS]

Options:
  --job-id JOB_ID          Retrieve cost for specific job
  --batch                  Process multiple jobs
  --max-jobs N             Maximum jobs to process (default: 10)
  --days-back N            Days back to look for jobs (default: 7)
  --force-refresh          Force refresh existing cost data
```

### cloud_cost_report.py Reporting

```bash
python cloud_cost_report.py COMMAND [OPTIONS]

Commands:
  job JOB_ID               Detailed cost summary for specific job
  trends                   Cost trends over time
  budget                   Budget performance analysis
  compare                  Provider cost comparison
  retrieve-costs           Retrieve missing actual costs

Options:
  --days N                 Number of days to analyze (default: 30)
  --provider PROVIDER      Filter by provider (AWS, GCP, Azure)
  --json                   Output in JSON format
```

## Troubleshooting

### Common Issues

#### 1. Cost Retrieval Failures
```bash
# Check if billing APIs are properly configured
python cost_tracker.py --job-id <job-id>

# Check cloud provider credentials
aws sts get-caller-identity    # AWS
gcloud auth list              # GCP
az account show               # Azure
```

#### 2. Budget Validation Errors
```bash
# Increase budget or reduce estimated runtime
python cloud_run.py --budget 20.00 --estimated-runtime 1.5

# Check spot price data is current
python find_cheapest_instance.py --no-interactive
```

#### 3. Database Issues
```bash
# Check database schema
sqlite3 cloud_jobs.db ".schema jobs"
sqlite3 cloud_jobs.db ".schema cost_tracking"

# Verify cost data
sqlite3 cloud_jobs.db "SELECT job_id, actual_cost, budget_limit FROM jobs WHERE actual_cost IS NOT NULL;"
```

### Debug Logging

Enable detailed logging for troubleshooting:

```bash
export PYTHONPATH=/path/to/cloud-scheduler
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from cost_tracker import CloudCostTracker
tracker = CloudCostTracker()
tracker.retrieve_job_cost('your-job-id')
"
```

## Advanced Usage

### Custom Cost Analysis

Extend the cost tracking system with custom analysis:

```python
from cloud_cost_report import CostReporter
from datetime import datetime, timedelta

reporter = CostReporter()

# Custom cost analysis
def analyze_weekend_costs():
    trends = reporter.generate_cost_trends(days=30)
    # Analyze trends data for weekend vs. weekday patterns
    return analysis

# Cost prediction accuracy
def cost_prediction_accuracy():
    jobs = reporter.job_manager.list_jobs(limit=100)
    accurate_jobs = []
    for job in jobs:
        if job.get('actual_cost') and job.get('estimated_cost'):
            accuracy = abs(job['actual_cost'] - job['estimated_cost']) / job['estimated_cost']
            if accuracy < 0.1:  # Within 10%
                accurate_jobs.append(job)
    return len(accurate_jobs) / len(jobs) * 100
```

### Integration with Monitoring

Monitor cost tracking performance:

```python
import logging
from cloud_cost_report import CostReporter

# Set up monitoring
logger = logging.getLogger('cost_monitoring')
reporter = CostReporter()

# Check for over-budget jobs
over_budget = reporter.job_manager.get_jobs_over_budget()
if over_budget:
    logger.warning(f"Found {len(over_budget)} jobs over budget")

# Check cost retrieval success rate
results = reporter.cost_tracker.batch_retrieve_costs(max_jobs=50)
success_rate = results['successful'] / results['processed'] * 100
logger.info(f"Cost retrieval success rate: {success_rate:.1f}%")
```

## Best Practices

### 1. Budget Management
- Set realistic budget limits based on historical data
- Use conservative runtime estimates for critical jobs
- Monitor budget success rates regularly

### 2. Cost Optimization
- Review cost trends weekly to identify patterns
- Compare provider costs for similar workloads
- Adjust hardware requirements based on cost analysis

### 3. Data Management
- Archive old cost data periodically
- Monitor database size growth
- Set up automated cost retrieval for completed jobs

### 4. Security
- Use least-privilege IAM policies for billing API access
- Regularly rotate cloud provider credentials
- Monitor billing API usage for unexpected patterns