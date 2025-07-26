"""Test configuration and fixtures for cloud-scheduler tests."""
import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "hardware": {
            "min_vcpu": 16,
            "max_vcpu": 32,
            "min_ram_gb": 64,
            "max_ram_gb": 256
        },
        "aws": {
            "key_name": "test-keypair",
            "security_group": "test-sg",
            "iam_role": "test-role",
            "max_price": 5.0,
            "disk_size_gb": 100,
            "s3_bucket": "test-bucket"
        },
        "gcp": {
            "project_id": "test-project",
            "service_account_email": "test@test-project.iam.gserviceaccount.com",
            "disk_size_gb": 100
        },
        "azure": {
            "subscription_id": "test-subscription",
            "resource_group": "test-rg", 
            "admin_password": "TestPass123!",
            "key_vault_name": "test-vault",
            "disk_size_gb": 100
        },
        "docker": {
            "enabled": True,
            "image": "test/computational:latest"
        }
    }


@pytest.fixture
def config_file(temp_dir, sample_config):
    """Create a temporary config file."""
    config_path = os.path.join(temp_dir, "config.json")
    with open(config_path, 'w') as f:
        json.dump(sample_config, f)
    return config_path


@pytest.fixture
def sample_spot_prices():
    """Sample spot price data for testing."""
    return [
        {
            "provider": "AWS",
            "instance": "r5.4xlarge",
            "region": "us-east-1",
            "vcpu": 16,
            "ram_gb": 128,
            "price_hr": 0.512,
            "price_per_core_hr": 0.032
        },
        {
            "provider": "GCP", 
            "instance": "n2-highmem-16",
            "region": "us-central1",
            "vcpu": 16,
            "ram_gb": 128,
            "price_hr": 0.489,
            "price_per_core_hr": 0.031
        },
        {
            "provider": "Azure",
            "instance": "Standard_E16s_v5",
            "region": "eastus",
            "vcpu": 16,
            "ram_gb": 128,
            "price_hr": 0.534,
            "price_per_core_hr": 0.033
        }
    ]


@pytest.fixture
def spot_prices_file(temp_dir, sample_spot_prices):
    """Create a temporary spot_prices.json file."""
    prices_path = os.path.join(temp_dir, "spot_prices.json")
    with open(prices_path, 'w') as f:
        json.dump(sample_spot_prices, f)
    return prices_path


@pytest.fixture
def job_input_dir(temp_dir):
    """Create a sample job input directory."""
    job_dir = os.path.join(temp_dir, "test_job")
    os.makedirs(job_dir)
    
    # Create sample input files
    with open(os.path.join(job_dir, "input.inp"), 'w') as f:
        f.write("# Sample computational input file\njob_type = computational\n")
    
    with open(os.path.join(job_dir, "run_calculation.py"), 'w') as f:
        f.write("#!/usr/bin/env python3\nprint('Running test calculation')\n")
    
    with open(os.path.join(job_dir, "large_file.dat"), 'w') as f:
        f.write("# Large data file - should be excluded from sync\n" + "x" * 1000)
    
    return job_dir


@pytest.fixture
def mock_aws_clients():
    """Mock AWS clients for testing."""
    with patch('boto3.client') as mock_client:
        # Mock S3 client
        s3_mock = MagicMock()
        s3_mock.upload_file.return_value = None
        s3_mock.put_object.return_value = None
        
        # Mock EC2 client
        ec2_mock = MagicMock()
        ec2_mock.describe_spot_price_history.return_value = {
            'SpotPrices': [
                {
                    'InstanceType': 'r5.4xlarge',
                    'SpotPrice': '0.512',
                    'AvailabilityZone': 'us-east-1a'
                }
            ]
        }
        
        def client_factory(service_name, **kwargs):
            if service_name == 's3':
                return s3_mock
            elif service_name == 'ec2':
                return ec2_mock
            return MagicMock()
        
        mock_client.side_effect = client_factory
        yield {'s3': s3_mock, 'ec2': ec2_mock}


@pytest.fixture
def mock_gcp_clients():
    """Mock GCP clients for testing."""
    with patch('googleapiclient.discovery.build') as mock_build:
        compute_mock = MagicMock()
        compute_mock.instances().list().execute.return_value = {
            'items': []
        }
        mock_build.return_value = compute_mock
        yield compute_mock


@pytest.fixture
def mock_subprocess():
    """Mock subprocess calls."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Success",
            stderr=""
        )
        yield mock_run