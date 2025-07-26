"""Tests for cost_tracker.py"""
import json
import pytest
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from cost_tracker import CloudCostTracker
from job_manager import JobManager


class TestCloudCostTracker:
    """Test CloudCostTracker functionality."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        yield db_path
        import os
        if os.path.exists(db_path):
            os.unlink(db_path)
    
    @pytest.fixture
    def job_manager(self, temp_db):
        """Create JobManager with temporary database."""
        return JobManager(temp_db)
    
    @pytest.fixture
    def sample_job(self, job_manager):
        """Create a sample job for testing."""
        job_config = {
            's3_bucket': 'test-bucket',
            'gdrive_path': 'test/path',
            'basis_set': 'aug-cc-pVDZ',
            'budget_limit': 10.0,
            'price_per_hour': 0.5
        }
        
        launch_result = {
            'status': 'completed',
            'provider': 'AWS',
            'instance_type': 'r5.4xlarge',
            'instance_id': 'i-123456789',
            'region': 'us-east-1',
            'spot_request_id': 'sir-123456'
        }
        
        job_id = 'test-job-123'
        job_manager.create_job(job_id, job_config, launch_result)
        
        # Set job as completed
        job_manager.update_job_status(job_id, 'completed')
        
        return job_id
    
    @pytest.fixture
    def cost_tracker(self, temp_db):
        """Create CloudCostTracker with temporary database."""
        config = {
            'aws': {'region': 'us-east-1'},
            'gcp': {'project_id': 'test-project'},
            'azure': {'subscription_id': 'test-subscription'}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            config_file = f.name
        
        # Mock the job manager to use our temp database
        with patch('cost_tracker.get_job_manager') as mock_get_jm:
            mock_get_jm.return_value = JobManager(temp_db)
            tracker = CloudCostTracker(config_file)
        
        yield tracker
        
        import os
        if os.path.exists(config_file):
            os.unlink(config_file)
    
    def test_init_aws_clients(self, cost_tracker):
        """Test AWS client initialization."""
        with patch('boto3.client') as mock_client:
            cost_tracker._init_aws_clients()
            assert mock_client.call_count >= 1
            assert cost_tracker.aws_cost_client is not None
    
    def test_init_gcp_clients(self, cost_tracker):
        """Test GCP client initialization."""
        with patch('cost_tracker.GOOGLE_AVAILABLE', True):
            with patch('cost_tracker.billing_v1.CloudBillingClient') as mock_client:
                cost_tracker._init_gcp_clients()
                mock_client.assert_called_once()
    
    def test_init_azure_clients(self, cost_tracker):
        """Test Azure client initialization."""
        with patch('cost_tracker.AZURE_AVAILABLE', True):
            with patch('cost_tracker.DefaultAzureCredential') as mock_cred:
                with patch('cost_tracker.CostManagementClient') as mock_client:
                    cost_tracker._init_azure_clients()
                    mock_client.assert_called_once()
    
    def test_get_aws_spot_cost_success(self, cost_tracker, sample_job):
        """Test successful AWS cost retrieval."""
        mock_response = {
            'ResultsByTime': [
                {
                    'TimePeriod': {
                        'Start': '2024-01-01',
                        'End': '2024-01-02'
                    },
                    'Groups': [
                        {
                            'Keys': ['i-123456789', 'SpotUsage:r5.4xlarge'],
                            'Metrics': {
                                'BlendedCost': {
                                    'Amount': '1.024',
                                    'Unit': 'USD'
                                },
                                'UsageQuantity': {
                                    'Amount': '2.0',
                                    'Unit': 'Hrs'
                                }
                            }
                        }
                    ]
                }
            ]
        }
        
        cost_tracker.aws_cost_client = MagicMock()
        cost_tracker.aws_cost_client.get_cost_and_usage.return_value = mock_response
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)
        
        result = cost_tracker.get_aws_spot_cost(
            sample_job, 'i-123456789', 'us-east-1', start_date, end_date
        )
        
        assert result is not None
        assert result['total_cost'] == 1.024
        assert result['provider'] == 'AWS'
        assert len(result['breakdown']) == 1
        assert result['breakdown'][0]['amount'] == 1.024
    
    def test_get_aws_spot_cost_no_data(self, cost_tracker, sample_job):
        """Test AWS cost retrieval with no data."""
        mock_response = {'ResultsByTime': []}
        
        cost_tracker.aws_cost_client = MagicMock()
        cost_tracker.aws_cost_client.get_cost_and_usage.return_value = mock_response
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)
        
        result = cost_tracker.get_aws_spot_cost(
            sample_job, 'i-123456789', 'us-east-1', start_date, end_date
        )
        
        assert result is None
    
    def test_get_aws_spot_cost_client_error(self, cost_tracker, sample_job):
        """Test AWS cost retrieval with client error."""
        cost_tracker.aws_cost_client = MagicMock()
        cost_tracker.aws_cost_client.get_cost_and_usage.side_effect = Exception("API Error")
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)
        
        result = cost_tracker.get_aws_spot_cost(
            sample_job, 'i-123456789', 'us-east-1', start_date, end_date
        )
        
        assert result is None
    
    def test_get_azure_spot_cost_success(self, cost_tracker, sample_job):
        """Test successful Azure cost retrieval."""
        mock_response = MagicMock()
        mock_response.rows = [
            [2.048, 'vm-test-123']  # cost, resource_id
        ]
        
        cost_tracker.azure_cost_client = MagicMock()
        cost_tracker.azure_cost_client.query.usage.return_value = mock_response
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)
        
        result = cost_tracker.get_azure_spot_cost(
            sample_job, 'vm-test-123', 'test-rg', start_date, end_date
        )
        
        assert result is not None
        assert result['total_cost'] == 2.048
        assert result['provider'] == 'Azure'
        assert len(result['breakdown']) == 1
    
    def test_retrieve_job_cost_aws(self, cost_tracker, sample_job, job_manager):
        """Test job cost retrieval for AWS."""
        # Mock AWS cost retrieval
        mock_cost_data = {
            'total_cost': 1.5,
            'breakdown': [{
                'provider': 'AWS',
                'cost_type': 'spot_compute',
                'amount': 1.5,
                'currency': 'USD',
                'billing_period_start': '2024-01-01',
                'billing_period_end': '2024-01-02',
                'raw_data': {}
            }],
            'provider': 'AWS'
        }
        
        with patch.object(cost_tracker, 'get_aws_spot_cost', return_value=mock_cost_data):
            result = cost_tracker.retrieve_job_cost(sample_job)
        
        assert result is True
        
        # Verify cost was updated in database
        job = job_manager.get_job(sample_job)
        assert job['actual_cost'] == 1.5
        assert job['cost_retrieved_at'] is not None
    
    def test_retrieve_job_cost_not_completed(self, cost_tracker, job_manager):
        """Test job cost retrieval for non-completed job."""
        # Create running job
        job_config = {'s3_bucket': 'test', 'budget_limit': 5.0}
        launch_result = {'status': 'running', 'provider': 'AWS', 'instance_type': 'r5.large', 'region': 'us-east-1'}
        job_id = 'running-job'
        
        job_manager.create_job(job_id, job_config, launch_result)
        
        result = cost_tracker.retrieve_job_cost(job_id)
        assert result is False
    
    def test_retrieve_job_cost_already_retrieved(self, cost_tracker, sample_job, job_manager):
        """Test job cost retrieval when cost already exists."""
        # Set actual cost
        job_manager.update_actual_cost(sample_job, 2.0)
        
        result = cost_tracker.retrieve_job_cost(sample_job)
        assert result is True  # Returns True because cost already exists
    
    def test_retrieve_job_cost_force_refresh(self, cost_tracker, sample_job, job_manager):
        """Test job cost retrieval with force refresh."""
        # Set actual cost
        job_manager.update_actual_cost(sample_job, 2.0)
        
        mock_cost_data = {
            'total_cost': 3.0,
            'breakdown': [],
            'provider': 'AWS'
        }
        
        with patch.object(cost_tracker, 'get_aws_spot_cost', return_value=mock_cost_data):
            result = cost_tracker.retrieve_job_cost(sample_job, force_refresh=True)
        
        assert result is True
        
        # Verify cost was updated
        job = job_manager.get_job(sample_job)
        assert job['actual_cost'] == 3.0
    
    def test_batch_retrieve_costs(self, cost_tracker, job_manager):
        """Test batch cost retrieval."""
        # Create multiple completed jobs
        job_ids = []
        for i in range(3):
            job_config = {'s3_bucket': 'test', 'budget_limit': 5.0}
            launch_result = {
                'status': 'completed', 
                'provider': 'AWS', 
                'instance_type': 'r5.large',
                'instance_id': f'i-{i}',
                'region': 'us-east-1'
            }
            job_id = f'batch-job-{i}'
            job_ids.append(job_id)
            
            job_manager.create_job(job_id, job_config, launch_result)
            job_manager.update_job_status(job_id, 'completed')
        
        # Mock cost retrieval for all jobs
        mock_cost_data = {
            'total_cost': 1.0,
            'breakdown': [],
            'provider': 'AWS'
        }
        
        with patch.object(cost_tracker, 'get_aws_spot_cost', return_value=mock_cost_data):
            results = cost_tracker.batch_retrieve_costs(max_jobs=5, days_back=1)
        
        assert results['processed'] == 3
        assert results['successful'] == 3
        assert results['failed'] == 0
        assert len(results['jobs']) == 3
    
    def test_batch_retrieve_costs_with_failures(self, cost_tracker, job_manager):
        """Test batch cost retrieval with some failures."""
        # Create jobs
        job_ids = []
        for i in range(2):
            job_config = {'s3_bucket': 'test', 'budget_limit': 5.0}
            launch_result = {
                'status': 'completed', 
                'provider': 'AWS', 
                'instance_type': 'r5.large',
                'instance_id': f'i-{i}',
                'region': 'us-east-1'
            }
            job_id = f'batch-job-{i}'
            job_ids.append(job_id)
            
            job_manager.create_job(job_id, job_config, launch_result)
            job_manager.update_job_status(job_id, 'completed')
        
        # Mock one success, one failure
        def mock_get_cost(job_id, *args):
            if 'batch-job-0' in job_id:
                return {'total_cost': 1.0, 'breakdown': [], 'provider': 'AWS'}
            return None
        
        with patch.object(cost_tracker, 'get_aws_spot_cost', side_effect=mock_get_cost):
            results = cost_tracker.batch_retrieve_costs(max_jobs=5, days_back=1)
        
        assert results['processed'] == 2
        assert results['successful'] == 1
        assert results['failed'] == 1
    
    def test_estimate_gcp_cost(self, cost_tracker):
        """Test GCP cost estimation (placeholder)."""
        result = cost_tracker._estimate_gcp_cost(
            'test-instance', 'test-project', 'us-central1-a',
            datetime.now(), datetime.now()
        )
        
        # Currently returns None as placeholder
        assert result is None
    
    def test_no_aws_client(self, cost_tracker, sample_job):
        """Test behavior when AWS client is not available."""
        cost_tracker.aws_cost_client = None
        
        result = cost_tracker.get_aws_spot_cost(
            sample_job, 'i-123', 'us-east-1', datetime.now(), datetime.now()
        )
        
        assert result is None
    
    def test_no_azure_client(self, cost_tracker, sample_job):
        """Test behavior when Azure client is not available."""
        cost_tracker.azure_cost_client = None
        
        result = cost_tracker.get_azure_spot_cost(
            sample_job, 'vm-test', 'test-rg', datetime.now(), datetime.now()
        )
        
        assert result is None
    
    def test_retrieve_job_cost_unsupported_provider(self, cost_tracker, job_manager):
        """Test job cost retrieval for unsupported provider."""
        job_config = {'s3_bucket': 'test', 'budget_limit': 5.0}
        launch_result = {
            'status': 'completed', 
            'provider': 'ORACLE',  # Unsupported
            'instance_type': 'test.large',
            'region': 'us-east-1'
        }
        job_id = 'unsupported-job'
        
        job_manager.create_job(job_id, job_config, launch_result)
        job_manager.update_job_status(job_id, 'completed')
        
        result = cost_tracker.retrieve_job_cost(job_id)
        assert result is False
    
    def test_gcp_cost_with_no_client(self, cost_tracker, sample_job):
        """Test GCP cost retrieval when client is not available."""
        cost_tracker.gcp_billing_client = None
        
        result = cost_tracker.get_gcp_spot_cost(
            sample_job, 'test-instance', 'test-project', 'us-central1-a',
            datetime.now(), datetime.now()
        )
        
        assert result is None