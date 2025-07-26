"""Unit tests for cloud_run.py functionality."""
import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from cloud_run import CloudJobManager


class TestCloudJobManager:
    """Test CloudJobManager functionality."""
    
    def test_job_manager_initialization(self, sample_config):
        """Test CloudJobManager initialization."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sample_config, f)
            config_path = f.name
        
        try:
            manager = CloudJobManager('test-bucket', config_path)
            assert manager.s3_bucket == 'test-bucket'
            assert manager.config == sample_config
            assert len(manager.job_id) == 8  # UUID truncated to 8 chars
        finally:
            os.unlink(config_path)
    
    @patch('boto3.client')
    def test_upload_job_files(self, mock_boto_client, job_input_dir):
        """Test S3 file upload functionality."""
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        
        manager = CloudJobManager('test-bucket')
        s3_path = manager.upload_job_files(job_input_dir)
        
        # Verify S3 upload calls
        assert mock_s3.upload_file.call_count >= 2  # Should upload input.inp and run_calculation.py
        
        # Verify FCIDUMP is excluded by default (shouldn't be uploaded)
        uploaded_files = [call[0][2] for call in mock_s3.upload_file.call_args_list]  # S3 keys
        fcidump_uploaded = any('FCIDUMP' in key for key in uploaded_files)
        assert not fcidump_uploaded, "FCIDUMP should be excluded from upload by default"
        
        # Verify S3 path format
        assert s3_path.startswith(f's3://test-bucket/{manager.job_id}/input/')
    
    def test_create_job_metadata(self):
        """Test job metadata creation."""
        manager = CloudJobManager('test-bucket')
        
        job_config = {
            'basis_set': 'aug-cc-pVTZ',
            'gdrive_path': 'custom/path',
            'shci_executable': './custom_shci',
            'environment': {'CUSTOM_VAR': 'value'}
        }
        
        s3_path = f's3://test-bucket/{manager.job_id}/input/'
        metadata = manager.create_job_metadata(job_config, s3_path)
        
        assert metadata['job_id'] == manager.job_id
        assert metadata['s3_input_path'] == s3_path
        assert metadata['s3_bucket'] == 'test-bucket'
        assert metadata['basis_set'] == 'aug-cc-pVTZ'
        assert metadata['gdrive_path'] == 'custom/path'
        assert metadata['shci_executable'] == './custom_shci'
        assert metadata['environment'] == {'CUSTOM_VAR': 'value'}
        assert 'timestamp' in metadata
    
    def test_create_custom_bootstrap_script(self, temp_dir):
        """Test custom bootstrap script generation."""
        # Create a mock bootstrap.sh
        bootstrap_content = '''#!/bin/bash
# Original bootstrap script
echo "Starting bootstrap"

# --- Get and Build Code ---
echo "Getting code"

# Output sync section
rclone sync "$OUTPUT_DIR" "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}"
'''
        
        bootstrap_path = os.path.join(temp_dir, 'bootstrap.sh')
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        
        manager = CloudJobManager('test-bucket')
        env_vars = {
            'JOB_ID': 'test123',
            'S3_INPUT_PATH': 's3://test-bucket/test123/input/',
            'GDRIVE_PATH': 'results/test'
        }
        
        custom_bootstrap = manager._create_custom_bootstrap(env_vars, bootstrap_path)
        
        # Verify environment variables are injected
        assert 'export JOB_ID="test123"' in custom_bootstrap
        assert 'export S3_INPUT_PATH="s3://test-bucket/test123/input/"' in custom_bootstrap
        
        # Verify S3 download section is added
        assert 'aws s3 sync "${S3_INPUT_PATH}" .' in custom_bootstrap
        
        # Verify FCIDUMP exclusion in rclone sync
        assert '--exclude "FCIDUMP"' in custom_bootstrap
        assert 'GDRIVE_PATH' in custom_bootstrap
        assert 'GDRIVE_DEST_DIR' not in custom_bootstrap  # Should be replaced


class TestJobConfigurationHandling:
    """Test job configuration processing."""
    
    def test_docker_configuration(self):
        """Test Docker configuration handling."""
        manager = CloudJobManager('test-bucket')
        
        # Test Docker enabled config
        job_config = {
            'use_docker': True,
            'docker_image': 'custom/image:latest'
        }
        
        env_vars = {
            'JOB_ID': 'test123',
            'S3_INPUT_PATH': 's3://test/path'
        }
        
        # Mock bootstrap script content
        with patch('builtins.open', mock_open(read_data='#!/bin/bash\necho "test"')):
            custom_script = manager._create_custom_bootstrap(env_vars, 'bootstrap-docker.sh')
            assert 'JOB_ID' in custom_script
    
    def test_exclude_patterns_handling(self, job_input_dir):
        """Test file exclusion pattern handling."""
        with patch('boto3.client') as mock_boto_client:
            mock_s3 = MagicMock()
            mock_boto_client.return_value = mock_s3
            
            manager = CloudJobManager('test-bucket')
            
            # Test custom exclude patterns
            exclude_patterns = ['*.log', 'FCIDUMP', 'temp*']
            manager.upload_job_files(job_input_dir, exclude_patterns)
            
            # Verify files were uploaded but excluded files were not
            uploaded_keys = [call[0][2] for call in mock_s3.upload_file.call_args_list]
            
            # Should not upload FCIDUMP
            fcidump_uploaded = any('FCIDUMP' in key for key in uploaded_keys)
            assert not fcidump_uploaded


class TestErrorHandling:
    """Test error handling in CloudJobManager."""
    
    @patch('boto3.client')
    def test_s3_upload_error_handling(self, mock_boto_client, job_input_dir):
        """Test handling of S3 upload errors."""
        mock_s3 = MagicMock()
        mock_s3.upload_file.side_effect = Exception("S3 upload failed")
        mock_boto_client.return_value = mock_s3
        
        manager = CloudJobManager('test-bucket')
        
        # Should raise exception on upload failure
        with pytest.raises(Exception):
            manager.upload_job_files(job_input_dir)
    
    def test_invalid_job_directory(self):
        """Test handling of invalid job directory."""
        manager = CloudJobManager('test-bucket')
        
        # Should handle non-existent directory gracefully
        with patch('pathlib.Path.rglob') as mock_rglob:
            mock_rglob.side_effect = FileNotFoundError("Directory not found")
            
            with pytest.raises(FileNotFoundError):
                manager.upload_job_files('/nonexistent/path')
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_launch_job_failure_handling(self, mock_exists, mock_subprocess, job_input_dir):
        """Test handling of job launch failures."""
        mock_exists.return_value = True
        mock_subprocess.return_value = MagicMock(returncode=1, stderr="Launch failed")
        
        with patch('boto3.client'):
            manager = CloudJobManager('test-bucket')
            
            job_config = {'basis_set': 'sto-3g'}
            
            with patch('cloud_run.get_job_manager') as mock_jm:
                mock_job_manager = MagicMock()
                mock_job_manager.create_job.return_value = True
                mock_jm.return_value = mock_job_manager
                
                result = manager.launch_job('AWS', 'r5.large', 'us-east-1', job_input_dir, job_config)
                
                assert result['status'] == 'failed'
                assert 'Launch failed' in result['error']


class TestBootstrapScriptModification:
    """Test bootstrap script modification logic."""
    
    def test_environment_variable_injection(self, temp_dir):
        """Test that environment variables are properly injected."""
        bootstrap_content = '''#!/bin/bash
echo "Starting setup"
'''
        
        bootstrap_path = os.path.join(temp_dir, 'test_bootstrap.sh')
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        
        manager = CloudJobManager('test-bucket')
        env_vars = {
            'JOB_ID': 'test123',
            'S3_BUCKET': 'my-bucket',
            'GDRIVE_PATH': 'results/test'
        }
        
        modified = manager._create_custom_bootstrap(env_vars, bootstrap_path)
        
        # Check that variables are exported at the top
        lines = modified.split('\n')
        var_lines = [line for line in lines if line.startswith('export')]
        
        assert any('JOB_ID="test123"' in line for line in var_lines)
        assert any('S3_BUCKET="my-bucket"' in line for line in var_lines)
        assert any('GDRIVE_PATH="results/test"' in line for line in var_lines)
    
    def test_s3_download_section_insertion(self, temp_dir):
        """Test S3 download section is properly inserted."""
        bootstrap_content = '''#!/bin/bash
echo "Setup"

# --- Get and Build Code ---
echo "Building"
'''
        
        bootstrap_path = os.path.join(temp_dir, 'test_bootstrap.sh')
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        
        manager = CloudJobManager('test-bucket')
        env_vars = {'S3_INPUT_PATH': 's3://bucket/path/'}
        
        modified = manager._create_custom_bootstrap(env_vars, bootstrap_path)
        
        # Should have S3 download section before "Get and Build Code"
        assert 'aws s3 sync "${S3_INPUT_PATH}" .' in modified
        assert 'mkdir -p job_input' in modified
        
        # Check order: S3 download should come before "Get and Build Code"
        s3_pos = modified.find('aws s3 sync')
        build_pos = modified.find('# --- Get and Build Code ---')
        assert s3_pos < build_pos, "S3 download should come before code building"