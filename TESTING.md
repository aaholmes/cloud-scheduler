# Testing Guide

This document provides comprehensive information about testing the Cloud Scheduler project.

## Overview

The Cloud Scheduler test suite includes:

- **Unit Tests**: Test individual functions and classes in isolation
- **Integration Tests**: Test interactions between components and external services  
- **Dry Run Tests**: Test the `--dry-run` functionality end-to-end
- **Credential Validation Tests**: Test authentication for dynamic instance discovery
- **Rate Limiting Tests**: Verify exponential backoff and API throttling
- **Mock Services**: Simulate AWS, GCP, and Azure APIs for reliable testing

## Quick Start

### Install Test Dependencies

```bash
pip install -r requirements-test.txt
```

### Run All Tests

```bash
# Using the test runner script
python run_tests.py

# Or directly with pytest
pytest tests/ -v --cov
```

### Run Specific Test Categories  

```bash
# Unit tests only
python run_tests.py --mode unit

# Integration tests only  
python run_tests.py --mode integration

# Dry run tests only
python run_tests.py --mode dry-run

# Credential validation tests only
python run_tests.py --mode auth

# Fast tests (no coverage)
python run_tests.py --mode fast
```

## Test Structure

```
tests/
├── unit/
│   ├── test_find_cheapest_instance.py  # Dynamic discovery tests
│   ├── test_credential_validation.py   # NEW: Authentication tests
│   ├── test_rate_limiting.py           # NEW: Rate limiting tests
│   ├── test_cloud_run.py
│   ├── test_cost_tracker.py
│   ├── test_job_manager.py
│   └── test_budget_validation.py
├── integration/
│   ├── test_cloud_providers.py         # Real API tests with auth
│   ├── test_dry_run.py                 # End-to-end dry run tests
│   └── test_s3_staging.py              # S3 integration tests
├── fixtures/
│   ├── mock_aws_responses.json         # Mock API responses
│   ├── mock_gcp_responses.json
│   ├── mock_azure_responses.json
│   └── invalid_credentials.json        # NEW: Credential test data
└── conftest.py                         # Test configuration
```

## New Testing Features

### Credential Validation Tests

The system now includes comprehensive tests for cloud provider authentication:

```bash
# Test credential validation without making API calls
pytest tests/unit/test_credential_validation.py -v

# Test with actual credentials (integration)
pytest tests/integration/test_cloud_providers.py::test_credential_validation -v
```

**What's tested:**
- AWS credential validation with proper error messages
- GCP service account authentication
- Azure DefaultAzureCredential handling
- Helpful error messages for common authentication issues

### Rate Limiting Tests

Tests verify the new rate limiting and exponential backoff features:

```bash
# Test rate limiting behavior
pytest tests/unit/test_rate_limiting.py -v
```

**What's tested:**
- Rate limit enforcement (calls per second)
- Burst limit handling
- Exponential backoff on API errors
- Retry logic with jitter

### Dynamic Discovery Tests

Enhanced tests for the new dynamic instance discovery:

```bash
# Test dynamic discovery with mocked APIs
pytest tests/unit/test_find_cheapest_instance.py::test_dynamic_discovery -v
```

**What's tested:**
- API calls to all cloud providers
- Instance filtering based on requirements
- Fallback behavior when APIs fail
- Credential validation before API calls

## Test Categories

### Unit Tests

**Credential Validation (`test_credential_validation.py`):**
```python
def test_aws_credential_validation():
    """Test AWS credential validation with various error conditions."""
    
def test_gcp_credential_validation():
    """Test GCP authentication with service accounts."""
    
def test_azure_credential_validation():
    """Test Azure DefaultAzureCredential authentication."""
```

**Rate Limiting (`test_rate_limiting.py`):**
```python
def test_rate_limit_enforcement():
    """Verify rate limiting prevents excessive API calls."""
    
def test_exponential_backoff():
    """Test exponential backoff on API errors."""
    
def test_burst_limit_handling():
    """Verify burst limit enforcement."""
```

**Dynamic Discovery (`test_find_cheapest_instance.py`):**
```python
def test_aws_instance_discovery():
    """Test AWS EC2 instance type discovery."""
    
def test_gcp_machine_type_discovery():
    """Test GCP machine type discovery."""
    
def test_azure_vm_size_discovery():
    """Test Azure VM size discovery with SDK."""
```

### Integration Tests

**Cloud Provider Authentication (`test_cloud_providers.py`):**
```bash
# These tests require actual cloud credentials
export AWS_PROFILE=test-profile
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
az login

pytest tests/integration/test_cloud_providers.py -v --auth-tests
```

**Dry Run End-to-End (`test_dry_run.py`):**
```bash
# Test complete workflow without launching instances
pytest tests/integration/test_dry_run.py -v
```

## Running Specific Test Categories

### Authentication Tests Only
```bash
# Unit tests for credential validation
pytest tests/unit/test_credential_validation.py -v

# Integration tests with real credentials
pytest tests/integration/test_cloud_providers.py::test_auth -v --slow
```

### Rate Limiting Tests
```bash
# Test rate limiting and backoff behavior
pytest tests/unit/test_rate_limiting.py -v --slow
```

### Dynamic Discovery Tests
```bash
# Test with mocked APIs
pytest tests/unit/test_find_cheapest_instance.py::test_dynamic_discovery -v

# Test with real APIs (requires credentials)
pytest tests/integration/test_cloud_providers.py::test_dynamic_discovery -v --slow
```

## Mock Data and Fixtures

### New Test Fixtures

**`fixtures/invalid_credentials.json`:**
```json
{
  "aws_invalid": {
    "error": "UnauthorizedOperation",
    "message": "AWS credentials not valid or insufficient permissions"
  },
  "gcp_invalid": {
    "error": "DefaultCredentialsError", 
    "message": "No GCP credentials available"
  },
  "azure_invalid": {
    "error": "AuthenticationError",
    "message": "No Azure subscriptions accessible"
  }
}
```

**Enhanced API Response Mocks:**
- `mock_aws_responses.json` - Updated with new EC2 instance types
- `mock_gcp_responses.json` - Updated with latest machine types  
- `mock_azure_responses.json` - Updated with current VM sizes

## Continuous Integration

### GitHub Actions Integration

The test suite now includes credential validation in CI:

```yaml
# .github/workflows/test.yml
- name: Test Credential Validation
  run: |
    python -m pytest tests/unit/test_credential_validation.py -v
    python -m pytest tests/unit/test_rate_limiting.py -v
```

**Note**: Integration tests with real cloud APIs are not run in CI to avoid credential management issues.

## Troubleshooting Test Issues

### Credential Test Failures

```bash
# Check if credentials are properly configured
aws sts get-caller-identity
gcloud auth list
az account show

# Run tests with debug output
pytest tests/unit/test_credential_validation.py -v -s --log-cli-level=DEBUG
```

### Rate Limiting Test Issues

```bash
# These tests may be slow due to intentional delays
pytest tests/unit/test_rate_limiting.py -v --timeout=60
```

### Mock vs Real API Tests

```bash
# Run only mock tests (fast)
pytest tests/unit/ -v -m "not slow"

# Run real API tests (requires credentials)
pytest tests/integration/ -v -m "slow" --auth-tests
```

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests
│   ├── test_find_cheapest_instance.py
│   ├── test_cloud_run.py
│   └── test_job_manager.py
├── integration/             # Integration tests
│   ├── test_s3_staging.py
│   ├── test_cloud_providers.py
│   └── test_dry_run.py
└── fixtures/                # Test data and mock responses
```

## Unit Tests

Unit tests focus on testing individual functions and classes with mocked dependencies.

### Price Discovery Tests (`test_find_cheapest_instance.py`)

Tests for the spot price discovery and filtering logic:

```python
# Test hardware requirements filtering
def test_filter_by_hardware_requirements():
    instances = [
        {"vcpu": 8, "ram_gb": 32, "price_hr": 0.2},
        {"vcpu": 16, "ram_gb": 64, "price_hr": 0.4}
    ]
    filtered = filter_by_hardware_requirements(instances, min_vcpu=16)
    assert len(filtered) == 1

# Test price sorting logic
def test_sort_instances_by_price():
    # Verify sorting by total price vs per-core price
```

### Job Management Tests (`test_cloud_run.py`)

Tests for the CloudJobManager class:

```python
# Test S3 file upload functionality
def test_upload_job_files(mock_s3, job_input_dir):
    manager = CloudJobManager('test-bucket')
    s3_path = manager.upload_job_files(job_input_dir)
    assert s3_path.startswith('s3://test-bucket/')

# Test bootstrap script generation
def test_create_custom_bootstrap_script():
    # Verify environment variables are injected correctly
```

### Database Tests (`test_job_manager.py`)

Tests for job state tracking:

```python
# Test job creation and retrieval
def test_create_job():
    jm = JobManager(':memory:')  # In-memory SQLite
    success = jm.create_job('test-job', config, launch_result)
    assert success
    
    job = jm.get_job('test-job')
    assert job['job_id'] == 'test-job'
```

## Integration Tests

Integration tests use mocked cloud services to test component interactions.

### S3 Staging Tests (`test_s3_staging.py`)

Tests S3 integration with moto (AWS mock):

```python
@mock_s3
def test_complete_s3_upload_workflow():
    # Creates real S3 bucket (mocked)
    s3_client = boto3.client('s3', region_name='us-east-1') 
    bucket_name = 'test-staging-bucket'
    s3_client.create_bucket(Bucket=bucket_name)
    
    # Test actual upload workflow
    manager = CloudJobManager(bucket_name)
    s3_path = manager.upload_job_files(job_input_dir)
    
    # Verify files exist in mocked S3
    response = s3_client.list_objects_v2(Bucket=bucket_name)
    assert 'Contents' in response
```

### Cloud Provider Tests (`test_cloud_providers.py`)

Tests cloud provider API integration:

```python
@patch('boto3.client')
def test_aws_spot_price_retrieval(mock_boto_client):
    # Mock AWS EC2 API responses
    mock_ec2.describe_spot_price_history.return_value = {
        'SpotPrices': [/* mock data */]
    }
    
    prices = get_aws_spot_prices('us-east-1')
    assert len(prices) > 0
    assert prices[0]['provider'] == 'AWS'
```

### Dry Run Tests (`test_dry_run.py`)

End-to-end tests for dry run functionality:

```python
def test_dry_run_complete_workflow():
    # Test complete dry run without launching instances
    result = manager.launch_job(
        'AWS', 'r5.4xlarge', 'us-east-1',
        job_input_dir, job_config, dry_run=True
    )
    
    assert result['status'] == 'dry_run_success'
    # Verify no actual S3 uploads occurred
    mock_s3.upload_file.assert_not_called()
```

## Test Fixtures

### Shared Fixtures (`conftest.py`)

Common test fixtures used across multiple test files:

```python
@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "hardware": {"min_vcpu": 16, "max_vcpu": 32},
        "aws": {"key_name": "test-keypair"},
        # ... other provider configs
    }

@pytest.fixture  
def job_input_dir(temp_dir):
    """Create sample job input directory."""
    job_dir = os.path.join(temp_dir, "test_job")
    os.makedirs(job_dir)
    
    # Create test files
    with open(os.path.join(job_dir, "input.inp"), 'w') as f:
        f.write("# Sample input file")
    
    return job_dir
```

## Mocking Strategy

### Cloud Provider APIs

We use comprehensive mocking for cloud provider APIs:

```python
# AWS (using moto)
@mock_s3
@mock_ec2
def test_aws_functionality():
    # Real boto3 calls against mocked services
    
# GCP (using unittest.mock)
@patch('googleapiclient.discovery.build')
def test_gcp_functionality(mock_build):
    mock_compute = MagicMock()
    mock_build.return_value = mock_compute
    
# Azure (using unittest.mock)
@patch('azure.mgmt.compute.ComputeManagementClient')
def test_azure_functionality(mock_client):
    mock_compute = MagicMock()
    mock_client.return_value = mock_compute
```

### File System Operations

```python
@pytest.fixture
def temp_dir():
    """Provide isolated temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
```

## Dry Run Testing

The `--dry-run` flag allows testing the complete workflow without launching actual cloud instances.

### Command Line Testing

```bash
# Test dry run via command line
python cloud_run.py my_job_files \
  --s3-bucket test-bucket \
  --from-spot-prices \
  --dry-run
```

### Expected Dry Run Output

```
=== DRY RUN MODE - NO INSTANCE WILL BE LAUNCHED ===
Preparing dry run for job abc12345
[DRY RUN] Would upload files from ./my_job_files to s3://test-bucket/abc12345/input/
[DRY RUN] Would save metadata to s3://test-bucket/abc12345/metadata.json
[DRY RUN] Metadata preview:
{
  "job_id": "abc12345",
  "s3_input_path": "s3://test-bucket/abc12345/input/",
  "basis_set": "aug-cc-pVDZ"
}
[DRY RUN] Would create job record in database for job abc12345
[DRY RUN] Provider: AWS, Instance: r5.4xlarge, Region: us-east-1
[DRY RUN] Would launch instance with command:
[DRY RUN] Command: python launch_job.py --provider AWS --instance r5.4xlarge --region us-east-1
[DRY RUN] Bootstrap script preview (first 500 chars):
#!/bin/bash
# Job-specific environment variables
export JOB_ID="abc12345"
export S3_BUCKET="test-bucket"
...

=== DRY RUN COMPLETED SUCCESSFULLY ===
Job ID: abc12345
Provider: AWS
Instance Type: r5.4xlarge
Region: us-east-1
S3 Path: s3://test-bucket/abc12345/input/
Google Drive Path: shci_jobs/abc12345

To actually launch this job, run the same command without --dry-run
```

## Running Tests

### Basic Test Commands

```bash
# Install dependencies and run all tests
python run_tests.py --install-deps

# Run specific test file
python run_tests.py --test tests/unit/test_cloud_run.py

# Run specific test method  
python run_tests.py --test tests/unit/test_cloud_run.py::TestCloudJobManager::test_upload_job_files

# Skip coverage for faster execution
python run_tests.py --no-cov
```

### CI/CD Integration

For continuous integration, use:

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run full test suite with coverage
pytest tests/ --cov --cov-report=xml

# Generate coverage report
coverage html
```

### Test Configuration

Key pytest configuration in `pytest.ini`:

```ini
[tool:pytest]
testpaths = tests
addopts = --verbose --tb=short --cov --cov-report=term-missing
filterwarnings = ignore::DeprecationWarning
```

## Test Coverage

Target coverage levels:

- **Overall**: >80%
- **Core modules**: >90% (find_cheapest_instance.py, cloud_run.py, job_manager.py)
- **Integration**: >70%

View coverage report:

```bash
# Generate HTML coverage report
pytest tests/ --cov --cov-report=html

# Open htmlcov/index.html in browser
open htmlcov/index.html
```

## Debugging Tests

### Running Individual Tests

```bash
# Run single test with detailed output
pytest tests/unit/test_cloud_run.py::TestCloudJobManager::test_upload_job_files -v -s

# Run with pdb debugger
pytest tests/unit/test_cloud_run.py::TestCloudJobManager::test_upload_job_files --pdb
```

### Common Issues

1. **Import Errors**: Ensure project root is in Python path
2. **Missing Dependencies**: Run `pip install -r requirements-test.txt`
3. **AWS Credentials**: Tests use mocked services, real credentials not needed
4. **File Permissions**: Ensure test files are readable

### Test Data Cleanup

Tests use temporary directories and in-memory databases by default. Cleanup is automatic, but for manual cleanup:

```bash
# Remove test artifacts
rm -rf htmlcov/
rm -f .coverage
rm -f cloud_jobs.db
rm -f spot_prices.json
rm -f launch_result.json
```

## Writing New Tests

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`  
- Test methods: `test_<functionality>`

### Example Test Structure

```python
"""Unit tests for new_module.py functionality."""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from new_module import NewClass


class TestNewClass:
    """Test NewClass functionality."""
    
    def test_basic_functionality(self):
        """Test basic functionality works."""
        obj = NewClass()
        result = obj.method()
        assert result == expected_value
    
    @patch('new_module.external_dependency')
    def test_with_mocking(self, mock_dep):
        """Test functionality with mocked dependencies."""
        mock_dep.return_value = "mocked_result"
        
        obj = NewClass()
        result = obj.method_using_dependency()
        
        assert result == "expected_result"
        mock_dep.assert_called_once()
```

### Best Practices

1. **Use fixtures** for common test data and setup
2. **Mock external dependencies** (APIs, file system, databases)
3. **Test both success and failure cases**
4. **Use descriptive test names** that explain what is being tested
5. **Keep tests focused** - one concept per test method
6. **Clean up resources** in test teardown (fixtures handle this automatically)

## Performance Testing

For performance-sensitive operations:

```python
import time

def test_performance_benchmark():
    """Test that operation completes within time limit."""
    start_time = time.time()
    
    # Operation to test
    result = expensive_operation()
    
    end_time = time.time()
    duration = end_time - start_time
    
    assert duration < 5.0, f"Operation took {duration}s, should be < 5s"
    assert result is not None
```

## Future Test Enhancements

Potential areas for test expansion:

1. **Load Testing**: Test with large job directories and many concurrent jobs
2. **Network Failure Simulation**: Test resilience to network issues  
3. **Cloud Provider Rate Limiting**: Test handling of API rate limits
4. **Security Testing**: Verify credential handling and secret management
5. **Cross-Platform Testing**: Test on different operating systems