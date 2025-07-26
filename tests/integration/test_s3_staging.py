"""Integration tests for S3 staging functionality."""
import json
import os
import pytest
import tempfile
from moto import mock_s3
import boto3
from unittest.mock import patch
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from cloud_run import CloudJobManager


@mock_s3
class TestS3Integration:
    """Test S3 staging integration with real AWS SDK calls (mocked)."""
    
    def setup_method(self):
        """Set up S3 mock for each test."""
        # Create mock S3 bucket
        self.s3_client = boto3.client('s3', region_name='us-east-1')
        self.bucket_name = 'test-staging-bucket'
        self.s3_client.create_bucket(Bucket=self.bucket_name)
    
    def test_complete_s3_upload_workflow(self, job_input_dir):
        """Test complete S3 upload workflow with real file operations."""
        manager = CloudJobManager(self.bucket_name)
        
        # Upload job files
        s3_path = manager.upload_job_files(job_input_dir)
        
        # Verify S3 path format
        assert s3_path == f's3://{self.bucket_name}/{manager.job_id}/input/'
        
        # Verify files were uploaded to S3
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=f'{manager.job_id}/input/'
        )
        
        assert 'Contents' in response
        uploaded_files = {obj['Key'] for obj in response['Contents']}
        
        # Verify expected files are present
        expected_files = {
            f'{manager.job_id}/input/input.inp',
            f'{manager.job_id}/input/run_calculation.py'
        }
        
        for expected in expected_files:
            assert expected in uploaded_files, f"Expected file {expected} not found in S3"
        
        # Verify FCIDUMP is excluded
        fcidump_files = {key for key in uploaded_files if 'FCIDUMP' in key}
        assert len(fcidump_files) == 0, "FCIDUMP files should be excluded from upload"
    
    def test_s3_metadata_upload(self, job_input_dir):
        """Test S3 metadata file upload."""
        manager = CloudJobManager(self.bucket_name)
        
        job_config = {
            'basis_set': 'aug-cc-pVTZ',
            'gdrive_path': 'test/results',
            'shci_executable': './test_shci'
        }
        
        s3_input_path = manager.upload_job_files(job_input_dir)
        metadata = manager.create_job_metadata(job_config, s3_input_path)
        
        # Upload metadata to S3 (simulate what launch_job does)
        metadata_key = f"{manager.job_id}/metadata.json"
        manager.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=metadata_key,
            Body=json.dumps(metadata, indent=2),
            ContentType='application/json'
        )
        
        # Verify metadata was uploaded
        response = manager.s3_client.get_object(Bucket=self.bucket_name, Key=metadata_key)
        uploaded_metadata = json.loads(response['Body'].read().decode('utf-8'))
        
        assert uploaded_metadata['job_id'] == manager.job_id
        assert uploaded_metadata['basis_set'] == 'aug-cc-pVTZ'
        assert uploaded_metadata['gdrive_path'] == 'test/results'
        assert uploaded_metadata['s3_input_path'] == s3_input_path
    
    def test_s3_file_exclusion_patterns(self, temp_dir):
        """Test custom file exclusion patterns."""
        # Create test directory with various file types
        job_dir = os.path.join(temp_dir, 'exclusion_test')
        os.makedirs(job_dir)
        
        test_files = {
            'input.inp': 'input file',
            'FCIDUMP': 'large fcidump data',
            'calculation.log': 'log data',
            'temp_file.tmp': 'temporary data',
            'backup.bak': 'backup data',
            'important.py': 'python script'
        }
        
        for filename, content in test_files.items():
            with open(os.path.join(job_dir, filename), 'w') as f:
                f.write(content)
        
        manager = CloudJobManager(self.bucket_name)
        
        # Upload with custom exclusion patterns
        exclude_patterns = ['*.log', 'FCIDUMP', '*.tmp', '*.bak']
        manager.upload_job_files(job_dir, exclude_patterns)
        
        # Verify only non-excluded files were uploaded
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=f'{manager.job_id}/input/'
        )
        
        uploaded_files = {obj['Key'].split('/')[-1] for obj in response['Contents']}
        expected_uploaded = {'input.inp', 'important.py'}
        excluded_files = {'FCIDUMP', 'calculation.log', 'temp_file.tmp', 'backup.bak'}
        
        assert uploaded_files == expected_uploaded
        assert not uploaded_files.intersection(excluded_files)
    
    def test_s3_large_file_handling(self, temp_dir):
        """Test handling of large files."""
        job_dir = os.path.join(temp_dir, 'large_file_test')
        os.makedirs(job_dir)
        
        # Create a moderately large file (1MB)
        large_file_path = os.path.join(job_dir, 'large_data.dat')
        with open(large_file_path, 'w') as f:
            f.write('x' * (1024 * 1024))  # 1MB of 'x' characters
        
        manager = CloudJobManager(self.bucket_name)
        s3_path = manager.upload_job_files(job_dir)
        
        # Verify large file was uploaded
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=f'{manager.job_id}/input/'
        )
        
        uploaded_files = {obj['Key'] for obj in response['Contents']}
        large_file_key = f'{manager.job_id}/input/large_data.dat'
        assert large_file_key in uploaded_files
        
        # Verify file size
        file_obj = next(obj for obj in response['Contents'] if obj['Key'] == large_file_key)
        assert file_obj['Size'] == 1024 * 1024
    
    def test_s3_directory_structure_preservation(self, temp_dir):
        """Test that directory structure is preserved in S3."""
        job_dir = os.path.join(temp_dir, 'nested_test')
        os.makedirs(job_dir)
        
        # Create nested directory structure
        nested_dirs = [
            'subdir1',
            'subdir1/subdir2',
            'configs'
        ]
        
        for dir_path in nested_dirs:
            full_path = os.path.join(job_dir, dir_path)
            os.makedirs(full_path, exist_ok=True)
        
        # Create files in nested directories
        test_files = {
            'root.txt': 'root level file',
            'subdir1/level1.txt': 'level 1 file',
            'subdir1/subdir2/level2.txt': 'level 2 file',
            'configs/config.json': '{"test": true}'
        }
        
        for rel_path, content in test_files.items():
            full_path = os.path.join(job_dir, rel_path)
            with open(full_path, 'w') as f:
                f.write(content)
        
        manager = CloudJobManager(self.bucket_name)
        manager.upload_job_files(job_dir)
        
        # Verify directory structure is preserved in S3
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=f'{manager.job_id}/input/'
        )
        
        uploaded_keys = {obj['Key'] for obj in response['Contents']}
        expected_keys = {
            f'{manager.job_id}/input/root.txt',
            f'{manager.job_id}/input/subdir1/level1.txt',
            f'{manager.job_id}/input/subdir1/subdir2/level2.txt',
            f'{manager.job_id}/input/configs/config.json'
        }
        
        assert uploaded_keys == expected_keys
    
    def test_s3_error_handling(self, job_input_dir):
        """Test S3 error handling."""
        manager = CloudJobManager(self.bucket_name)
        
        # Test with non-existent bucket
        manager.s3_bucket = 'non-existent-bucket-12345'
        
        with pytest.raises(Exception):
            manager.upload_job_files(job_input_dir)
    
    def test_s3_concurrent_uploads(self, temp_dir):
        """Test handling of concurrent job uploads."""
        job_dir = os.path.join(temp_dir, 'concurrent_test')
        os.makedirs(job_dir)
        
        with open(os.path.join(job_dir, 'test.txt'), 'w') as f:
            f.write('test data')
        
        # Create multiple managers (simulating concurrent jobs)
        managers = [CloudJobManager(self.bucket_name) for _ in range(3)]
        
        # Upload files from all managers
        s3_paths = []
        for manager in managers:
            s3_path = manager.upload_job_files(job_dir)
            s3_paths.append(s3_path)
        
        # Verify all uploads succeeded and are isolated
        assert len(set(s3_paths)) == 3  # All paths should be unique
        
        # Verify all files exist in S3
        for manager in managers:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f'{manager.job_id}/input/'
            )
            assert 'Contents' in response
            assert len(response['Contents']) >= 1


@mock_s3
class TestS3BootstrapIntegration:
    """Test S3 integration with bootstrap script generation."""
    
    def setup_method(self):
        """Set up S3 mock for each test."""
        self.s3_client = boto3.client('s3', region_name='us-east-1')
        self.bucket_name = 'test-bootstrap-bucket'
        self.s3_client.create_bucket(Bucket=self.bucket_name)
    
    def test_bootstrap_s3_environment_variables(self, job_input_dir, temp_dir):
        """Test that bootstrap script receives correct S3 environment variables."""
        # Create mock bootstrap.sh
        bootstrap_content = '''#!/bin/bash
echo "Starting bootstrap"

# --- Get and Build Code ---
echo "Getting code"
'''
        
        bootstrap_path = os.path.join(temp_dir, 'bootstrap.sh')
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        
        manager = CloudJobManager(self.bucket_name)
        s3_path = manager.upload_job_files(job_input_dir)
        
        env_vars = {
            'JOB_ID': manager.job_id,
            'S3_BUCKET': self.bucket_name,
            'S3_INPUT_PATH': s3_path,
            'GDRIVE_PATH': 'test/results'
        }
        
        modified_bootstrap = manager._create_custom_bootstrap(env_vars, bootstrap_path)
        
        # Verify S3-specific environment variables
        assert f'export S3_BUCKET="{self.bucket_name}"' in modified_bootstrap
        assert f'export S3_INPUT_PATH="{s3_path}"' in modified_bootstrap
        
        # Verify S3 sync command is present
        assert 'aws s3 sync "${S3_INPUT_PATH}" .' in modified_bootstrap
        assert '--exclude "*.log"' in modified_bootstrap