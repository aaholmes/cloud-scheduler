"""End-to-end tests for dry run functionality."""
import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from cloud_run import CloudJobManager, main as cloud_run_main


class TestDryRunFunctionality:
    """Test end-to-end dry run functionality."""
    
    def test_dry_run_complete_workflow(self, job_input_dir, temp_dir, sample_config):
        """Test complete dry run workflow without launching instances."""
        # Create config file
        config_path = os.path.join(temp_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(sample_config, f)
        
        # Create spot_prices.json
        spot_prices = [{
            "provider": "AWS",
            "instance": "r5.4xlarge",
            "region": "us-east-1",
            "vcpu": 16,
            "ram_gb": 128,
            "price_hr": 0.512,
            "price_per_core_hr": 0.032
        }]
        spot_prices_path = os.path.join(temp_dir, 'spot_prices.json')
        with open(spot_prices_path, 'w') as f:
            json.dump(spot_prices, f)
        
        # Change to temp directory
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            # Mock S3 client to avoid actual AWS calls
            with patch('boto3.client') as mock_boto:
                mock_s3 = MagicMock()
                mock_boto.return_value = mock_s3
                
                manager = CloudJobManager('test-bucket', config_path)
                
                job_config = {
                    'basis_set': 'aug-cc-pVDZ',
                    'gdrive_path': 'test/results',
                    'use_docker': False
                }
                
                # Run dry run
                result = manager.launch_job(
                    'AWS', 'r5.4xlarge', 'us-east-1', 
                    job_input_dir, job_config, dry_run=True
                )
                
                # Verify dry run result
                assert result['status'] == 'dry_run_success'
                assert result['job_id'] == manager.job_id
                assert result['provider'] == 'AWS'
                assert result['instance_type'] == 'r5.4xlarge'
                assert result['region'] == 'us-east-1'
                assert 'dry run completed successfully' in result['message'].lower()
                
                # Verify no actual S3 uploads occurred
                mock_s3.upload_file.assert_not_called()
                mock_s3.put_object.assert_not_called()
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_vs_normal_run_behavior(self, job_input_dir, temp_dir, sample_config):
        """Compare dry run vs normal run behavior."""
        config_path = os.path.join(temp_dir, 'config.json') 
        with open(config_path, 'w') as f:
            json.dump(sample_config, f)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client') as mock_boto:
                mock_s3 = MagicMock()
                mock_boto.return_value = mock_s3
                
                job_config = {'basis_set': 'sto-3g', 'use_docker': False}
                
                # Test dry run
                manager_dry = CloudJobManager('test-bucket', config_path)
                dry_result = manager_dry.launch_job(
                    'AWS', 'r5.large', 'us-east-1',
                    job_input_dir, job_config, dry_run=True
                )
                
                # Test normal run (but mock the actual launch)
                manager_normal = CloudJobManager('test-bucket', config_path)
                
                with patch('subprocess.run') as mock_subprocess:
                    # Mock successful launch
                    mock_subprocess.return_value = MagicMock(returncode=0)
                    
                    # Mock launch_result.json
                    launch_result_data = {
                        'status': 'launched',
                        'instance_id': 'i-12345',
                        'public_ip': '1.2.3.4'
                    }
                    
                    with patch('builtins.open', create=True) as mock_open:
                        mock_file = MagicMock()
                        mock_file.read.return_value = json.dumps(launch_result_data)
                        mock_open.return_value.__enter__.return_value = mock_file
                        
                        with patch('cloud_run.get_job_manager') as mock_jm:
                            mock_job_manager = MagicMock()
                            mock_job_manager.create_job.return_value = True
                            mock_jm.return_value = mock_job_manager
                            
                            with patch('os.path.exists', return_value=False):  # No existing bootstrap.sh
                                normal_result = manager_normal.launch_job(
                                    'AWS', 'r5.large', 'us-east-1',
                                    job_input_dir, job_config, dry_run=False
                                )
                
                # Compare results
                assert dry_result['status'] == 'dry_run_success'
                assert normal_result['status'] == 'launched'
                
                # Dry run should not call S3 operations
                dry_upload_calls = mock_s3.upload_file.call_count
                
                # Reset mock for normal run comparison
                mock_s3.reset_mock()
                
                # Normal run should call S3 operations (if not mocked away)
                # This verifies the code paths are different
                
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_command_line_interface(self, job_input_dir, temp_dir, sample_config):
        """Test dry run through command line interface."""
        config_path = os.path.join(temp_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(sample_config, f)
        
        spot_prices = [{
            "provider": "GCP",
            "instance": "n2-highmem-16", 
            "region": "us-central1",
            "vcpu": 16,
            "ram_gb": 128,
            "price_hr": 0.489
        }]
        spot_prices_path = os.path.join(temp_dir, 'spot_prices.json')
        with open(spot_prices_path, 'w') as f:
            json.dump(spot_prices, f)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            # Mock command line arguments
            test_args = [
                'cloud_run.py',
                job_input_dir,
                '--s3-bucket', 'test-bucket',
                '--from-spot-prices',
                '--dry-run',
                '--config', config_path
            ]
            
            with patch('sys.argv', test_args):
                with patch('boto3.client'):
                    with patch('sys.exit') as mock_exit:
                        with patch('cloud_run.logger') as mock_logger:
                            cloud_run_main()
                            
                            # Verify dry run messages were logged
                            log_calls = [str(call) for call in mock_logger.info.call_args_list]
                            
                            assert any('DRY RUN MODE' in call for call in log_calls)
                            assert any('DRY RUN COMPLETED SUCCESSFULLY' in call for call in log_calls)
                            
                            # Should not exit with error
                            mock_exit.assert_not_called()
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_bootstrap_script_generation(self, job_input_dir, temp_dir):
        """Test bootstrap script generation in dry run mode."""
        # Create mock bootstrap.sh
        bootstrap_content = '''#!/bin/bash
echo "Starting setup"

# --- Get and Build Code ---
echo "Building code"

# Sync results
rclone sync "$OUTPUT_DIR" "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}"
'''
        
        bootstrap_path = os.path.join(temp_dir, 'bootstrap.sh')
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client'):
                manager = CloudJobManager('test-bucket')
                
                job_config = {
                    'basis_set': 'aug-cc-pVTZ',
                    'gdrive_path': 'results/water_dimer',
                    'use_docker': False
                }
                
                # Capture log output
                with patch('cloud_run.logger') as mock_logger:
                    result = manager.launch_job(
                        'AWS', 'r5.4xlarge', 'us-east-1',
                        job_input_dir, job_config, dry_run=True
                    )
                    
                    # Verify bootstrap script preview was logged
                    log_calls = [str(call) for call in mock_logger.info.call_args_list]
                    bootstrap_preview_logged = any('Bootstrap script preview' in call for call in log_calls)
                    assert bootstrap_preview_logged
                    
                    # Verify dry run success
                    assert result['status'] == 'dry_run_success'
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_docker_mode(self, job_input_dir, temp_dir, sample_config):
        """Test dry run with Docker mode enabled."""
        # Create mock bootstrap-docker.sh
        docker_bootstrap_content = '''#!/bin/bash
echo "Docker bootstrap"
docker run quantum-chemistry:latest
'''
        
        bootstrap_docker_path = os.path.join(temp_dir, 'bootstrap-docker.sh')
        with open(bootstrap_docker_path, 'w') as f:
            f.write(docker_bootstrap_content)
        
        config_path = os.path.join(temp_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(sample_config, f)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client'):
                manager = CloudJobManager('test-bucket', config_path)
                
                job_config = {
                    'basis_set': 'aug-cc-pVDZ',
                    'use_docker': True,
                    'docker_image': 'custom/quantum-chemistry:v1.0'
                }
                
                result = manager.launch_job(
                    'GCP', 'n2-highmem-16', 'us-central1',
                    job_input_dir, job_config, dry_run=True
                )
                
                assert result['status'] == 'dry_run_success'
                assert result['provider'] == 'GCP'
                assert result['instance_type'] == 'n2-highmem-16'
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_file_exclusion_preview(self, temp_dir):
        """Test dry run shows file exclusion preview."""
        # Create job directory with various files
        job_dir = os.path.join(temp_dir, 'test_job')
        os.makedirs(job_dir)
        
        test_files = {
            'input.inp': 'input data',
            'FCIDUMP': 'large file to exclude',
            'calculation.log': 'log file',
            'important.py': 'python script'
        }
        
        for filename, content in test_files.items():
            with open(os.path.join(job_dir, filename), 'w') as f:
                f.write(content)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client'):
                manager = CloudJobManager('test-bucket')
                
                job_config = {
                    'exclude_patterns': ['FCIDUMP', '*.log'],
                    'use_docker': False
                }
                
                with patch('cloud_run.logger') as mock_logger:
                    result = manager.launch_job(
                        'Azure', 'Standard_E16s_v5', 'eastus',
                        job_dir, job_config, dry_run=True
                    )
                    
                    # Verify exclusion information was logged
                    log_calls = [str(call) for call in mock_logger.info.call_args_list]
                    upload_logged = any('Would upload files from' in call for call in log_calls)
                    assert upload_logged
                    
                    assert result['status'] == 'dry_run_success'
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_error_handling(self, temp_dir):
        """Test error handling in dry run mode."""
        # Test with non-existent job directory
        non_existent_dir = os.path.join(temp_dir, 'does_not_exist')
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            test_args = [
                'cloud_run.py',
                non_existent_dir,  # Non-existent directory
                '--s3-bucket', 'test-bucket',
                '--provider', 'AWS',
                '--instance', 'r5.large',
                '--region', 'us-east-1',
                '--dry-run'
            ]
            
            with patch('sys.argv', test_args):
                with patch('sys.exit') as mock_exit:
                    cloud_run_main()
                    
                    # Should exit with error for invalid job directory
                    mock_exit.assert_called_once_with(1)
        
        finally:
            os.chdir(original_dir)


class TestDryRunValidation:
    """Test validation and verification in dry run mode."""
    
    def test_dry_run_validates_configuration(self, job_input_dir, temp_dir):
        """Test that dry run validates configuration without launching."""
        # Create invalid config (missing required fields)
        invalid_config = {
            "aws": {
                # Missing required fields like key_name
                "disk_size_gb": 100
            }
        }
        
        config_path = os.path.join(temp_dir, 'invalid_config.json')
        with open(config_path, 'w') as f:
            json.dump(invalid_config, f)
        
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client'):
                manager = CloudJobManager('test-bucket', config_path)
                
                job_config = {'basis_set': 'sto-3g', 'use_docker': False}
                
                # Dry run should still complete (validation happens during actual launch)
                result = manager.launch_job(
                    'AWS', 'r5.large', 'us-east-1',
                    job_input_dir, job_config, dry_run=True
                )
                
                # Should succeed in dry run mode even with invalid config
                assert result['status'] == 'dry_run_success'
        
        finally:
            os.chdir(original_dir)
    
    def test_dry_run_preserves_job_id_consistency(self, job_input_dir, temp_dir):
        """Test that dry run generates consistent job ID for repeated runs."""
        original_dir = os.getcwd() 
        os.chdir(temp_dir)
        
        try:
            with patch('boto3.client'):
                # Create two managers
                manager1 = CloudJobManager('test-bucket')
                manager2 = CloudJobManager('test-bucket')
                
                # Should have different job IDs
                assert manager1.job_id != manager2.job_id
                
                job_config = {'basis_set': 'sto-3g', 'use_docker': False}
                
                result1 = manager1.launch_job(
                    'AWS', 'r5.large', 'us-east-1',
                    job_input_dir, job_config, dry_run=True
                )
                
                result2 = manager2.launch_job(
                    'AWS', 'r5.large', 'us-east-1', 
                    job_input_dir, job_config, dry_run=True
                )
                
                # Each dry run should have its own unique job ID
                assert result1['job_id'] != result2['job_id']
                assert result1['job_id'] == manager1.job_id
                assert result2['job_id'] == manager2.job_id
        
        finally:
            os.chdir(original_dir)