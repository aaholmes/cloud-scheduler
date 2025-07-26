# Troubleshooting Guide

This guide covers common issues with the Cloud Scheduler's dynamic instance discovery system and credential validation.

## Authentication Issues

### AWS Credential Problems

**Error: "AWS credentials not valid or insufficient permissions"**

**Cause**: Invalid or expired AWS credentials, or insufficient IAM permissions.

**Solutions:**
```bash
# Check current credentials
aws sts get-caller-identity

# Reconfigure credentials
aws configure

# Test EC2 permissions (required for dynamic discovery)
aws ec2 describe-regions --max-items 1
```

**Required IAM Permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeRegions",
        "ec2:DescribeSpotPriceHistory"
      ],
      "Resource": "*"
    }
  ]
}
```

**Error: "UnauthorizedOperation"**

**Cause**: IAM user/role lacks necessary EC2 permissions.

**Solution:**
1. Attach the `AmazonEC2ReadOnlyAccess` policy to your IAM user/role
2. Or create a custom policy with the permissions above

### GCP Credential Problems

**Error: "No GCP credentials available. Run 'gcloud auth application-default login'"**

**Cause**: Application Default Credentials not configured.

**Solutions:**
```bash
# For user credentials (development)
gcloud auth application-default login

# For service account (production)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# Test credentials
gcloud auth list
```

**Error: "GCP credentials lack sufficient permissions"**

**Cause**: Service account or user lacks Compute Engine permissions.

**Required Permissions:**
- `compute.machineTypes.list`
- `compute.zones.list`

**Solution:**
```bash
# Grant Compute Viewer role
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="user:your-email@domain.com" \
  --role="roles/compute.viewer"
```

### Azure Credential Problems

**Error: "No Azure subscriptions accessible with current credentials"**

**Cause**: Not logged in to Azure or insufficient subscription permissions.

**Solutions:**
```bash
# Login to Azure
az login

# List available subscriptions
az account list --output table

# Set default subscription
az account set --subscription "subscription-name-or-id"

# Test access
az vm list-sizes --location eastus --output table
```

**Error: "Azure SDK not installed"**

**Cause**: Missing Azure SDK dependencies.

**Solution:**
```bash
pip install azure-identity azure-mgmt-compute azure-mgmt-resource
```

**Error: "Authentication failed" (in containers)**

**Cause**: Container doesn't have access to Azure credentials.

**Solutions:**
1. **Mount credential directory:**
   ```bash
   docker run -v ~/.azure:/root/.azure:ro your-image
   ```

2. **Use environment variables:**
   ```bash
   docker run \
     -e AZURE_CLIENT_ID=your-client-id \
     -e AZURE_CLIENT_SECRET=your-secret \
     -e AZURE_TENANT_ID=your-tenant-id \
     your-image
   ```

## Dynamic Discovery Issues

### Rate Limiting

**Message: "Rate limit burst exceeded, sleeping for X seconds"**

**Cause**: API calls exceeded burst limit to prevent quota issues.

**Action**: This is normal behavior. The system will automatically retry after the sleep period.

**Message: "API call failed (attempt X/3), retrying in X seconds"**

**Cause**: Temporary API error or rate limiting.

**Action**: The system uses exponential backoff and will retry automatically. No user action needed.

### API Discovery Failures

**Warning: "Failed to query AWS instance types dynamically: [error]"**

**Cause**: API call failed, using fallback instance types.

**Solutions:**
1. Check internet connectivity
2. Verify AWS credentials and permissions
3. Check if AWS service is experiencing outages
4. System will use basic fallback instances automatically

**Info: "Found 0 instances meeting hardware requirements"**

**Cause**: Hardware requirements too restrictive.

**Solutions:**
```bash
# Check what's available with broader criteria
python find_cheapest_instance.py --min-vcpu 1 --max-vcpu 128 --min-ram 1 --max-ram 1024

# Adjust your requirements
python find_cheapest_instance.py --min-vcpu 8 --max-vcpu 64 --min-ram 16 --max-ram 512
```

## Network and Connectivity Issues

### Firewall/Proxy Issues

**Error: "Connection timeout" or "SSL verification failed"**

**Cause**: Corporate firewall or proxy blocking cloud APIs.

**Solutions:**
```bash
# Configure proxy for AWS CLI
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080

# Configure proxy for gcloud
gcloud config set proxy/type http
gcloud config set proxy/address proxy.company.com
gcloud config set proxy/port 8080

# Configure proxy for Azure CLI
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
```

### DNS Resolution Issues

**Error: "Name or service not known"**

**Cause**: DNS resolution failing for cloud API endpoints.

**Solutions:**
1. Check DNS configuration: `nslookup ec2.amazonaws.com`
2. Try alternative DNS servers: `export NAMESERVER=8.8.8.8`
3. Check /etc/hosts for conflicts

## Container-Specific Issues

### Docker Authentication

**Error: "Unable to locate credentials" (in container)**

**Cause**: Credentials not mounted or accessible in container.

**Solutions:**
```bash
# Mount all credential directories
docker run \
  -v ~/.aws:/root/.aws:ro \
  -v ~/.config/gcloud:/root/.config/gcloud:ro \
  -v ~/.azure:/root/.azure:ro \
  your-image

# Verify mounts worked
docker exec -it container_name ls -la /root/.aws/
```

### Environment Variable Issues

**Error: "Environment variable not set"**

**Solutions:**
```bash
# Pass environment variables to container
docker run \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  -e GOOGLE_APPLICATION_CREDENTIALS \
  -e AZURE_CLIENT_ID \
  -e AZURE_CLIENT_SECRET \
  -e AZURE_TENANT_ID \
  your-image
```

## Configuration Issues

### Missing Configuration Files

**Error: "Configuration file not found"**

**Solutions:**
```bash
# Create config from example
cp config.example.json config.json

# Edit with your settings
nano config.json
```

### Invalid JSON Configuration

**Error: "JSON decode error"**

**Solutions:**
```bash
# Validate JSON syntax
python -m json.tool config.json

# Common issues:
# - Missing quotes around strings
# - Trailing commas
# - Unescaped special characters
```

## Performance Issues

### Slow Dynamic Discovery

**Issue**: Instance discovery takes a long time.

**Causes and Solutions:**
1. **Many instance types**: System queries all available types
   - Use specific hardware requirements to filter results
   - Consider using `--no-interactive` mode

2. **Rate limiting active**: System is throttling API calls
   - This is normal to prevent quota issues
   - Wait time varies by cloud provider

3. **Network latency**: Slow connection to cloud APIs
   - Check internet connection speed
   - Consider running from cloud instance in same region

### Memory Issues

**Error: "MemoryError" during discovery**

**Cause**: Large number of instance types consuming memory.

**Solutions:**
```bash
# Use more restrictive filters
python find_cheapest_instance.py --min-vcpu 16 --max-vcpu 32

# Monitor memory usage
python -c "
import psutil
print(f'Memory usage: {psutil.virtual_memory().percent}%')
"
```

## Getting Help

### Enable Debug Logging

```bash
# Enable verbose logging
export PYTHONPATH=.
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from find_cheapest_instance import get_aws_instance_types
print(get_aws_instance_types())
"
```

### Test Individual Components

```bash
# Test AWS discovery only
python -c "from find_cheapest_instance import get_aws_instance_types; print(len(get_aws_instance_types()))"

# Test GCP discovery only
python -c "from find_cheapest_instance import get_gcp_instance_types; print(len(get_gcp_instance_types()))"

# Test Azure discovery only
python -c "from find_cheapest_instance import get_azure_instance_types; print(len(get_azure_instance_types()))"
```

### Collect Diagnostic Information

```bash
# System information
python --version
pip list | grep -E "(boto3|google|azure)"

# Credential status
aws sts get-caller-identity 2>&1
gcloud auth list 2>&1
az account show 2>&1

# Network connectivity
curl -I https://ec2.amazonaws.com/ 2>&1
curl -I https://compute.googleapis.com/ 2>&1
curl -I https://management.azure.com/ 2>&1
```

### Common Error Patterns

**Pattern**: API calls work individually but fail in batch
**Solution**: Rate limiting is working correctly, be patient

**Pattern**: Works locally but fails in container
**Solution**: Check credential mounting and environment variables

**Pattern**: Works for one cloud provider but not others
**Solution**: Check credentials and permissions for failing provider

**Pattern**: Worked before but suddenly fails
**Solution**: Check for credential expiration or policy changes

## Report Issues

When reporting issues, please include:

1. **Error message**: Complete error output
2. **Command used**: Exact command that failed
3. **Environment**: OS, Python version, package versions
4. **Credentials**: Which cloud providers are configured (don't include actual credentials)
5. **Network**: Any firewall/proxy configuration
6. **Diagnostic output**: Results from diagnostic commands above

This information helps diagnose issues quickly and accurately.