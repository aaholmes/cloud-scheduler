# Configuration Guide

The cloud scheduler supports flexible configuration through JSON files and command-line arguments, making it easy to adapt for different calculation types without editing source code.

## Configuration Methods

### 1. Configuration Files

Hardware requirements and cloud provider settings are stored in JSON configuration files.

**Default location:** `config.json`

**Basic structure:**
```json
{
  "hardware": {
    "min_vcpu": 16,
    "max_vcpu": 32,
    "min_ram_gb": 64,
    "max_ram_gb": 256
  },
  "aws": {
    "key_name": "my-ec2-keypair",
    "security_group": "cloud-scheduler-sg",
    "iam_role": "cloud-scheduler-role",
    "max_price": 5.0,
    "disk_size_gb": 100,
    "s3_bucket": "my-shci-jobs"
  },
  "gcp": {
    "project_id": "my-gcp-project",
    "service_account_email": "cloud-scheduler@my-gcp-project.iam.gserviceaccount.com",
    "disk_size_gb": 100
  },
  "azure": {
    "subscription_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "resource_group": "cloud-scheduler-rg",
    "admin_password": "ChangeMe123!@#",
    "key_vault_name": "cloud-scheduler-vault",
    "disk_size_gb": 100
  }
}
```

### 2. Command-Line Arguments

Override configuration file settings with command-line arguments:

**Hardware requirements:**
```bash
python find_cheapest_instance.py --min-vcpu 8 --max-vcpu 16 --min-ram 32 --max-ram 128
python cloud_run.py my_job --min-vcpu 32 --max-vcpu 64 --min-ram 256 --max-ram 512
```

**Custom configuration file:**
```bash
python find_cheapest_instance.py --config my_custom_config.json
python cloud_run.py my_job --config config_profiles/large_calculation.json
```

## Configuration Profiles

Pre-configured profiles for common calculation types are available in `config_profiles/`:

### Small Calculations (`small_calculation.json`)
- **Use case:** Quick tests, small molecules, basis set optimization
- **Resources:** 4-16 vCPUs, 16-64GB RAM
- **Max cost:** $2.00/hour
- **Storage:** 50GB

```bash
python cloud_run.py my_small_job --config config_profiles/small_calculation.json
```

### Large Calculations (`large_calculation.json`)
- **Use case:** Production runs, large molecules, high accuracy
- **Resources:** 32-128 vCPUs, 256-1024GB RAM  
- **Max cost:** $20.00/hour
- **Storage:** 500GB

```bash
python cloud_run.py my_large_job --config config_profiles/large_calculation.json
```

### Memory-Intensive Calculations (`memory_intensive.json`)
- **Use case:** SHCI with large active spaces, dense matrices
- **Resources:** 16-64 vCPUs, 128-512GB RAM
- **Max cost:** $15.00/hour
- **Storage:** 200GB

```bash
python cloud_run.py my_memory_job --config config_profiles/memory_intensive.json
```

## Hardware Configuration Options

### CPU Requirements

- **`min_vcpu`**: Minimum number of virtual CPUs
- **`max_vcpu`**: Maximum number of virtual CPUs
- **Purpose**: Controls computational power and parallelization

**Examples:**
```bash
# CPU-intensive calculation
--min-vcpu 32 --max-vcpu 64

# Small test calculation  
--min-vcpu 4 --max-vcpu 8
```

### Memory Requirements

- **`min_ram_gb`**: Minimum RAM in gigabytes
- **`max_ram_gb`**: Maximum RAM in gigabytes
- **Purpose**: Ensures sufficient memory for large matrices and data structures

**Examples:**
```bash
# Memory-intensive SHCI
--min-ram 256 --max-ram 512

# Small molecule calculation
--min-ram 16 --max-ram 64
```

## Cloud Provider Configuration

### AWS Settings

```json
{
  "aws": {
    "key_name": "my-ec2-keypair",          // SSH key pair name
    "security_group": "cloud-scheduler-sg", // Security group name
    "iam_role": "cloud-scheduler-role",     // IAM role for instances
    "max_price": 5.0,                      // Maximum spot price
    "disk_size_gb": 100,                   // Root disk size
    "s3_bucket": "my-shci-jobs"            // S3 bucket for file staging
  }
}
```

### GCP Settings

```json
{
  "gcp": {
    "project_id": "my-gcp-project",                                        // GCP project ID
    "service_account_email": "cloud-scheduler@my-project.iam.gserviceaccount.com", // Service account
    "disk_size_gb": 100                                                   // Boot disk size
  }
}
```

### Azure Settings

```json
{
  "azure": {
    "subscription_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", // Azure subscription
    "resource_group": "cloud-scheduler-rg",                    // Resource group
    "admin_password": "ComplexPassword123!",                   // VM admin password
    "key_vault_name": "cloud-scheduler-vault",                 // Key vault for secrets
    "disk_size_gb": 100                                        // OS disk size
  }
}
```

## Configuration Precedence

Settings are applied in this order (highest to lowest priority):

1. **Command-line arguments** (highest priority)
2. **Configuration file settings**
3. **Default values** (lowest priority)

**Example:**
```bash
# Config file has min_vcpu: 16, but command line overrides to 8
python find_cheapest_instance.py --config my_config.json --min-vcpu 8
```

## Creating Custom Profiles

### Step 1: Copy Example Configuration
```bash
cp config.example.json my_custom_config.json
```

### Step 2: Modify Hardware Requirements
```json
{
  "hardware": {
    "min_vcpu": 64,      // For highly parallel calculations
    "max_vcpu": 128,
    "min_ram_gb": 512,   // For large active spaces
    "max_ram_gb": 1024
  }
}
```

### Step 3: Adjust Cost Limits
```json
{
  "aws": {
    "max_price": 25.0,   // Higher budget for large calculations
    "disk_size_gb": 1000 // More storage for output files
  }
}
```

### Step 4: Use Custom Profile
```bash
python cloud_run.py my_calculation --config my_custom_config.json --from-spot-prices
```

## Dynamic Configuration

The system now features **dynamic instance discovery** that automatically queries all cloud providers for available instance types instead of using hardcoded lists.

### Dynamic Instance Discovery
**NEW FEATURE**: The system dynamically discovers ALL available instance types from cloud provider APIs:

- **AWS**: Queries EC2 `describe_instance_types` API for real-time instance catalog
- **GCP**: Queries Compute Engine `machineTypes.list` API for current offerings
- **Azure**: Uses Azure SDK `resource_skus.list` API for VM size discovery

**Benefits:**
- Always discovers the latest instance types
- No maintenance of hardcoded instance lists
- Automatic filtering based on your requirements
- Graceful fallback if APIs are unavailable

### Rate Limiting and Security
**NEW FEATURE**: Built-in rate limiting with exponential backoff prevents API quota issues:

```python
# Rate limiting configuration
AWS_RATE_LIMIT = 10 calls/second, 50 burst limit
GCP_RATE_LIMIT = 10 calls/second, 30 burst limit
AZURE_RATE_LIMIT = SDK built-in throttling
```

**Credential Validation**: All cloud provider credentials are validated before API calls with helpful error messages.

### Automatic Instance Discovery
When using `--from-spot-prices`, the system will:
1. **Validate credentials** for all configured cloud providers
2. **Query APIs** with rate limiting to discover available instance types
3. **Filter instances** based on your hardware requirements
4. **Compare prices** across all providers
5. **Present interactive selection menu** with optimized options
6. **Launch your chosen instance** with full configuration

```bash
# System automatically finds instances matching these requirements
python cloud_run.py my_job \
  --s3-bucket my-bucket \
  --from-spot-prices \
  --min-vcpu 32 \
  --min-ram 256
```

### Smart Defaults
If hardware requirements aren't specified:
- Uses values from config file `hardware` section
- Falls back to built-in defaults (16-32 vCPUs, 64-256GB RAM)
- **NEW**: Dynamically discovers instances matching these requirements from live APIs

### Error Handling and Fallbacks
**Robust Error Handling**: If dynamic discovery fails for any provider:
- System provides detailed error messages for credential issues
- Falls back to basic instance set to ensure functionality
- Logs warnings but continues with available providers
- Implements exponential backoff for temporary API issues

## Validation and Error Handling

The system validates configuration and provides helpful error messages:

**Invalid ranges:**
```bash
$ python find_cheapest_instance.py --min-vcpu 32 --max-vcpu 16
ERROR: Minimum vCPUs cannot be greater than maximum vCPUs
```

**Missing configuration:**
```bash
$ python cloud_run.py my_job --provider AWS
ERROR: AWS key_name not specified in config file
```

**No matching instances:**
```bash
$ python find_cheapest_instance.py --min-vcpu 256
INFO: Found 0 instances meeting hardware requirements
```

**NEW: Credential Validation Errors:**
```bash
# AWS credential issues
ERROR: AWS credentials not valid or insufficient permissions: UnauthorizedOperation

# GCP credential issues
ERROR: No GCP credentials available. Run 'gcloud auth application-default login'

# Azure credential issues
ERROR: No Azure subscriptions accessible with current credentials
```

**NEW: API Discovery Errors:**
```bash
# Rate limiting
INFO: Rate limit burst exceeded, sleeping for 45.2s

# Fallback behavior
WARNING: Failed to query AWS instance types dynamically: [error]
INFO: Found 15 AWS instance types matching requirements (using fallback)
```

## Best Practices

### 1. Use Configuration Profiles
Create profiles for different calculation types rather than specifying requirements each time:

```bash
# Good: Reusable profile
python cloud_run.py job1 --config profiles/large_calc.json

# Less optimal: Repeated arguments
python cloud_run.py job1 --min-vcpu 32 --max-vcpu 64 --min-ram 256
```

### 2. Set Realistic Ranges
Allow flexibility in instance selection:

```bash
# Good: Flexible range
--min-vcpu 16 --max-vcpu 32

# Less optimal: Too narrow
--min-vcpu 31 --max-vcpu 32
```

### 3. Monitor Costs
Set appropriate price limits:

```json
{
  "aws": {
    "max_price": 5.0  // Prevents expensive instances
  }
}
```

### 4. Version Control Configurations
Store configuration profiles in version control:

```bash
git add config_profiles/
git commit -m "Add calculation profiles"
```

This ensures reproducible research and easy sharing between team members.

## Troubleshooting

### No Instances Found
```bash
# Check what instances are available with broader criteria
python find_cheapest_instance.py --min-vcpu 1 --max-vcpu 128 --min-ram 1 --max-ram 1024
```

### Configuration File Issues
```bash
# Validate JSON syntax
python -m json.tool config.json

# Test configuration loading
python -c "from find_cheapest_instance import load_hardware_config; print(load_hardware_config('config.json'))"
```

### Instance Launch Failures
Check that configuration matches your cloud provider setup:
- AWS: Verify key pair, security group, and IAM role exist
- GCP: Confirm project ID and service account permissions
- Azure: Check subscription ID and resource group access