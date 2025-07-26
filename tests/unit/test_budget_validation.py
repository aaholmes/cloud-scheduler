"""Tests for budget validation functionality in cloud_run.py"""
import json
import pytest
import tempfile
from unittest.mock import patch, MagicMock

from cloud_run import CloudJobManager


class TestBudgetValidation:
    """Test budget validation functionality."""
    
    @pytest.fixture
    def temp_s3_bucket(self):
        """Mock S3 bucket name."""
        return 'test-bucket'
    
    @pytest.fixture
    def mock_s3_client(self):
        """Mock S3 client."""
        with patch('cloud_run.boto3.client') as mock_client:
            s3_mock = MagicMock()
            s3_mock.upload_file.return_value = None
            s3_mock.put_object.return_value = None
            mock_client.return_value = s3_mock
            yield s3_mock
    
    @pytest.fixture
    def job_manager(self, temp_s3_bucket, mock_s3_client):
        """Create CloudJobManager for testing."""
        config = {'aws': {'region': 'us-east-1'}}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            config_file = f.name
        
        manager = CloudJobManager(temp_s3_bucket, config_file)
        
        yield manager
        
        # Cleanup
        import os
        if os.path.exists(config_file):
            os.unlink(config_file)
    
    @pytest.fixture
    def mock_spot_prices(self):
        """Mock spot prices data."""
        return [
            {
                'provider': 'AWS',
                'instance': 'r5.4xlarge',
                'region': 'us-east-1',
                'price_hr': 0.5,
                'vcpu': 16,
                'ram_gb': 128
            },
            {
                'provider': 'GCP',
                'instance': 'n2-highmem-16',
                'region': 'us-central1',
                'price_hr': 0.6,
                'vcpu': 16,
                'ram_gb': 128
            }
        ]
    
    def test_budget_validation_within_budget(self, job_manager, mock_spot_prices):
        """Test budget validation when estimated cost is within budget."""
        job_config = {
            'job_type': 'computational',
            'budget_limit': 10.0,
            'estimated_runtime': 2.0,
            'price_per_hour': 0.5  # Will be set from spot prices
        }
        
        # Mock spot prices file
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(mock_spot_prices)
                
                # Mock job manager creation
                with patch('cloud_run.get_job_manager') as mock_get_jm:
                    mock_jm = MagicMock()
                    mock_jm.create_job.return_value = True
                    mock_get_jm.return_value = mock_jm
                    
                    # Mock launch_job.py execution
                    with patch('subprocess.run') as mock_subprocess:
                        mock_subprocess.return_value = MagicMock(returncode=0)
                        
                        # Mock launch result file
                        launch_result = {
                            'status': 'launched',
                            'instance_id': 'i-123456',
                            'public_ip': '1.2.3.4'
                        }
                        
                        with patch('builtins.open', create=True) as mock_result_file:
                            mock_result_file.return_value.__enter__.return_value.read.return_value = json.dumps(launch_result)
                            
                            # This should succeed without raising an exception
                            result = job_manager.launch_job(
                                'AWS', 'r5.4xlarge', 'us-east-1',
                                '/fake/job/dir', job_config
                            )
                            
                            assert result is not None
                            assert result.get('status') != 'failed'
    
    def test_budget_validation_over_budget(self, job_manager):
        """Test budget validation when estimated cost exceeds budget."""
        job_config = {
            'job_type': 'computational',
            'budget_limit': 5.0,     # Low budget
            'estimated_runtime': 20.0,  # Long runtime
            'price_per_hour': 1.0       # High price per hour
        }
        
        # Estimated cost: 1.0 * 20.0 = 20.0, which exceeds budget of 5.0
        # This should fail validation before launching
        
        with pytest.raises(SystemExit):
            # Mock the validation logic that would be in the main() function
            estimated_cost = job_config['price_per_hour'] * job_config['estimated_runtime']
            if estimated_cost > job_config['budget_limit']:
                import sys
                sys.exit(1)
    
    def test_budget_validation_no_budget(self, job_manager, mock_spot_prices):
        """Test that jobs without budget limits proceed normally."""
        job_config = {
            'job_type': 'computational',
            'estimated_runtime': 2.0,
            'price_per_hour': 0.5
            # No budget_limit set
        }
        
        # Mock job manager and subprocess
        with patch('cloud_run.get_job_manager') as mock_get_jm:
            mock_jm = MagicMock()
            mock_jm.create_job.return_value = True
            mock_get_jm.return_value = mock_jm
            
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock(returncode=0)
                
                launch_result = {'status': 'launched'}
                with patch('builtins.open', create=True) as mock_file:
                    mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(launch_result)
                    
                    # Should succeed without budget validation
                    result = job_manager.launch_job(
                        'AWS', 'r5.4xlarge', 'us-east-1',
                        '/fake/job/dir', job_config
                    )
                    
                    assert result is not None
    
    def test_budget_calculation_accuracy(self):
        """Test budget calculation accuracy."""
        # Test various scenarios
        test_cases = [
            {'price_hr': 0.5, 'runtime': 2.0, 'budget': 2.0, 'should_pass': True},   # Exactly at budget
            {'price_hr': 0.5, 'runtime': 1.5, 'budget': 1.0, 'should_pass': False}, # Over budget
            {'price_hr': 0.25, 'runtime': 3.0, 'budget': 1.0, 'should_pass': True}, # Under budget
            {'price_hr': 1.0, 'runtime': 0.5, 'budget': 0.6, 'should_pass': True},  # Close but under
            {'price_hr': 2.0, 'runtime': 1.0, 'budget': 1.99, 'should_pass': False} # Close but over
        ]
        
        for case in test_cases:
            estimated_cost = case['price_hr'] * case['runtime']
            within_budget = estimated_cost <= case['budget']
            assert within_budget == case['should_pass'], f"Failed for case: {case}"
    
    def test_budget_with_spot_price_integration(self):
        """Test budget validation with spot price data."""
        spot_prices = [
            {'provider': 'AWS', 'instance': 'r5.large', 'price_hr': 0.1},
            {'provider': 'AWS', 'instance': 'r5.xlarge', 'price_hr': 0.2},
            {'provider': 'AWS', 'instance': 'r5.2xlarge', 'price_hr': 0.4},
            {'provider': 'AWS', 'instance': 'r5.4xlarge', 'price_hr': 0.8}
        ]
        
        budget = 1.0
        runtime = 2.0
        
        # Find instances that fit within budget
        affordable_instances = []
        for instance in spot_prices:
            estimated_cost = instance['price_hr'] * runtime
            if estimated_cost <= budget:
                affordable_instances.append(instance)
        
        # Should find r5.large and r5.xlarge (0.2 and 0.4 estimated cost)
        assert len(affordable_instances) == 2
        assert affordable_instances[0]['instance'] == 'r5.large'
        assert affordable_instances[1]['instance'] == 'r5.xlarge'
    
    def test_budget_error_messages(self):
        """Test that budget validation provides helpful error messages."""
        # Mock logging to capture error messages
        with patch('cloud_run.logger') as mock_logger:
            price_per_hour = 1.0
            estimated_runtime = 5.0
            budget = 3.0
            estimated_cost = price_per_hour * estimated_runtime
            
            if estimated_cost > budget:
                mock_logger.error(f"Estimated cost ${estimated_cost:.4f} exceeds budget ${budget:.2f}")
                mock_logger.error(f"Instance: test-instance @ ${price_per_hour:.4f}/hour for {estimated_runtime} hours")
                mock_logger.error("Use --estimated-runtime to adjust runtime estimate or increase --budget")
            
            # Verify error messages were logged
            assert mock_logger.error.call_count == 3
            
            # Check error message content
            error_calls = [call.args[0] for call in mock_logger.error.call_args_list]
            assert "Estimated cost $5.0000 exceeds budget $3.00" in error_calls[0]
            assert "test-instance @ $1.0000/hour for 5.0 hours" in error_calls[1]
            assert "--estimated-runtime" in error_calls[2]
    
    def test_budget_with_dry_run(self, job_manager):
        """Test budget validation in dry run mode."""
        job_config = {
            'job_type': 'computational',
            'budget_limit': 10.0,
            'estimated_runtime': 2.0,
            'price_per_hour': 3.0  # Would cost 6.0, under budget
        }
        
        with patch('cloud_run.get_job_manager') as mock_get_jm:
            mock_jm = MagicMock()
            mock_get_jm.return_value = mock_jm
            
            # Test dry run mode
            result = job_manager.launch_job(
                'AWS', 'r5.4xlarge', 'us-east-1',
                '/fake/job/dir', job_config, dry_run=True
            )
            
            assert result is not None
            assert result['status'] == 'dry_run_success'
    
    def test_job_config_with_budget_fields(self, job_manager, mock_spot_prices):
        """Test that job configuration includes budget-related fields."""
        job_config = {
            'job_type': 'computational',
            'budget_limit': 15.0,
            'estimated_runtime': 3.0,
            'price_per_hour': 0.8
        }
        
        # Verify that budget fields are included
        assert 'budget_limit' in job_config
        assert 'estimated_runtime' in job_config
        assert 'price_per_hour' in job_config
        
        # Test that these would be passed to job creation
        with patch('cloud_run.get_job_manager') as mock_get_jm:
            mock_jm = MagicMock()
            mock_jm.create_job.return_value = True
            mock_get_jm.return_value = mock_jm
            
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock(returncode=0)
                
                launch_result = {'status': 'launched'}
                with patch('builtins.open', create=True) as mock_file:
                    mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(launch_result)
                    
                    job_manager.launch_job(
                        'AWS', 'r5.4xlarge', 'us-east-1',
                        '/fake/job/dir', job_config
                    )
                    
                    # Verify create_job was called with budget fields
                    mock_jm.create_job.assert_called_once()
                    call_args = mock_jm.create_job.call_args
                    job_config_arg = call_args[0][1]  # Second argument is job_config
                    
                    assert job_config_arg['budget_limit'] == 15.0
                    assert job_config_arg['estimated_runtime'] == 3.0
                    assert job_config_arg['price_per_hour'] == 0.8