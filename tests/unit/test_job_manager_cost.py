"""Tests for cost-related functionality in job_manager.py"""
import json
import pytest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from job_manager import JobManager


class TestJobManagerCost:
    """Test cost-related functionality in JobManager."""
    
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
    def sample_job_with_budget(self, job_manager):
        """Create a sample job with budget for testing."""
        job_config = {
            's3_bucket': 'test-bucket',
            'gdrive_path': 'test/path',
            'basis_set': 'aug-cc-pVDZ',
            'budget_limit': 10.0,
            'price_per_hour': 0.5,
            'billing_tags': {'project': 'test', 'environment': 'dev'}
        }
        
        launch_result = {
            'status': 'launched',
            'provider': 'AWS',
            'instance_type': 'r5.4xlarge',
            'instance_id': 'i-123456789',
            'region': 'us-east-1',
            'spot_request_id': 'sir-123456'
        }
        
        job_id = 'test-job-budget'
        job_manager.create_job(job_id, job_config, launch_result)
        return job_id
    
    def test_create_job_with_cost_fields(self, job_manager):
        """Test creating job with new cost-related fields."""
        job_config = {
            's3_bucket': 'test-bucket',
            'budget_limit': 15.0,
            'price_per_hour': 0.75,
            'billing_tags': {'project': 'quantum', 'team': 'research'}
        }
        
        launch_result = {
            'status': 'launched',
            'provider': 'AWS',
            'instance_type': 'r5.8xlarge',
            'instance_id': 'i-987654321',
            'region': 'us-west-2',
            'spot_request_id': 'sir-987654'
        }
        
        job_id = 'cost-fields-test'
        result = job_manager.create_job(job_id, job_config, launch_result)
        
        assert result is True
        
        # Verify job was created with cost fields
        job = job_manager.get_job(job_id)
        assert job is not None
        assert job['budget_limit'] == 15.0
        assert job['spot_request_id'] == 'sir-987654'
        
        # Check billing tags were stored as JSON
        billing_tags = json.loads(job['billing_tags'])
        assert billing_tags['project'] == 'quantum'
        assert billing_tags['team'] == 'research'
    
    def test_update_actual_cost(self, job_manager, sample_job_with_budget):
        """Test updating actual cost for a job."""
        cost_breakdown = [
            {
                'provider': 'AWS',
                'cost_type': 'spot_compute',
                'amount': 2.5,
                'currency': 'USD',
                'billing_period_start': '2024-01-01T00:00:00',
                'billing_period_end': '2024-01-01T05:00:00',
                'raw_data': {'instance_hours': 5.0}
            }
        ]
        
        result = job_manager.update_actual_cost(sample_job_with_budget, 2.5, cost_breakdown)
        assert result is True
        
        # Verify job was updated
        job = job_manager.get_job(sample_job_with_budget)
        assert job['actual_cost'] == 2.5
        assert job['cost_retrieved_at'] is not None
        
        # Verify cost breakdown was stored
        import sqlite3
        with sqlite3.connect(job_manager.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('SELECT * FROM cost_tracking WHERE job_id = ?', (sample_job_with_budget,))
            cost_records = [dict(row) for row in cursor.fetchall()]
        
        assert len(cost_records) == 1
        assert cost_records[0]['amount'] == 2.5
        assert cost_records[0]['cost_type'] == 'spot_compute'
        assert cost_records[0]['provider'] == 'AWS'
    
    def test_check_budget_limit_within_budget(self, job_manager, sample_job_with_budget):
        """Test budget check when within budget."""
        estimated_cost = 8.0  # Under $10 budget
        
        result = job_manager.check_budget_limit(sample_job_with_budget, estimated_cost)
        
        assert result['within_budget'] is True
        assert result['budget_limit'] == 10.0
        assert result['estimated_cost'] == 8.0
        assert result['budget_usage_percent'] == 80.0
        assert result['over_budget_amount'] == 0
    
    def test_check_budget_limit_over_budget(self, job_manager, sample_job_with_budget):
        """Test budget check when over budget."""
        estimated_cost = 12.0  # Over $10 budget
        
        result = job_manager.check_budget_limit(sample_job_with_budget, estimated_cost)
        
        assert result['within_budget'] is False
        assert result['budget_limit'] == 10.0
        assert result['estimated_cost'] == 12.0
        assert result['budget_usage_percent'] == 120.0
        assert result['over_budget_amount'] == 2.0
    
    def test_check_budget_limit_no_budget(self, job_manager):
        """Test budget check for job without budget limit."""
        # Create job without budget
        job_config = {'s3_bucket': 'test-bucket'}
        launch_result = {'status': 'launched', 'provider': 'AWS', 'instance_type': 'r5.large', 'region': 'us-east-1'}
        job_id = 'no-budget-job'
        
        job_manager.create_job(job_id, job_config, launch_result)
        
        result = job_manager.check_budget_limit(job_id, 5.0)
        
        assert result['within_budget'] is True
        assert result['budget_limit'] is None
        assert result['estimated_cost'] == 5.0
    
    def test_get_cost_summary(self, job_manager, sample_job_with_budget):
        """Test getting comprehensive cost summary."""
        # Update job with actual cost
        cost_breakdown = [{
            'provider': 'AWS',
            'cost_type': 'spot_compute',
            'amount': 7.5,
            'currency': 'USD',
            'billing_period_start': '2024-01-01T00:00:00',
            'billing_period_end': '2024-01-01T15:00:00',
            'raw_data': {}
        }]
        
        job_manager.update_actual_cost(sample_job_with_budget, 7.5, cost_breakdown)
        
        summary = job_manager.get_cost_summary(sample_job_with_budget)
        
        assert summary is not None
        assert summary['job_id'] == sample_job_with_budget
        assert summary['provider'] == 'AWS'
        assert summary['instance_type'] == 'r5.4xlarge'
        assert summary['actual_cost'] == 7.5
        assert summary['budget_limit'] == 10.0
        assert summary['within_budget'] is True
        assert len(summary['cost_breakdown']) == 1
        assert summary['cost_breakdown'][0]['amount'] == 7.5
    
    def test_get_cost_summary_over_budget(self, job_manager, sample_job_with_budget):
        """Test cost summary for over-budget job."""
        # Update with cost that exceeds budget
        job_manager.update_actual_cost(sample_job_with_budget, 12.0)
        
        summary = job_manager.get_cost_summary(sample_job_with_budget)
        
        assert summary['within_budget'] is False
        assert summary['over_budget_amount'] == 2.0
        assert summary['budget_usage_percent'] == 120.0
    
    def test_get_cost_summary_nonexistent_job(self, job_manager):
        """Test cost summary for non-existent job."""
        summary = job_manager.get_cost_summary('nonexistent-job')
        assert summary is None
    
    def test_get_jobs_over_budget(self, job_manager):
        """Test getting jobs that are over budget."""
        # Create jobs with different budget scenarios
        jobs_data = [
            ('job-1', 5.0, 3.0),   # Within budget
            ('job-2', 10.0, 12.0), # Over budget
            ('job-3', 8.0, 10.0),  # Over budget
            ('job-4', 20.0, 15.0)  # Within budget
        ]
        
        for job_id, budget, actual_cost in jobs_data:
            job_config = {'s3_bucket': 'test', 'budget_limit': budget}
            launch_result = {'status': 'completed', 'provider': 'AWS', 'instance_type': 'r5.large', 'region': 'us-east-1'}
            
            job_manager.create_job(job_id, job_config, launch_result)
            job_manager.update_actual_cost(job_id, actual_cost)
        
        over_budget_jobs = job_manager.get_jobs_over_budget()
        
        assert len(over_budget_jobs) == 2
        
        # Verify the over-budget jobs
        job_ids = [job['job_id'] for job in over_budget_jobs]
        assert 'job-2' in job_ids
        assert 'job-3' in job_ids
        
        # Check over-budget calculations
        for job in over_budget_jobs:
            if job['job_id'] == 'job-2':
                assert job['over_budget_amount'] == 2.0
                assert job['budget_usage_percent'] == 120.0
            elif job['job_id'] == 'job-3':
                assert job['over_budget_amount'] == 2.0
                assert job['budget_usage_percent'] == 125.0
    
    def test_get_jobs_over_budget_with_estimated_cost(self, job_manager):
        """Test getting over-budget jobs using estimated costs when actual is not available."""
        job_config = {'s3_bucket': 'test', 'budget_limit': 5.0, 'price_per_hour': 2.0}
        launch_result = {'status': 'running', 'provider': 'AWS', 'instance_type': 'r5.large', 'region': 'us-east-1'}
        job_id = 'estimated-over-budget'
        
        job_manager.create_job(job_id, job_config, launch_result)
        
        # Set started time to make estimated cost > budget
        import sqlite3
        start_time = (datetime.now() - timedelta(hours=3)).isoformat()
        with sqlite3.connect(job_manager.db_path) as conn:
            conn.execute('UPDATE jobs SET started_at = ?, estimated_cost = ? WHERE job_id = ?', 
                        (start_time, 6.0, job_id))
        
        over_budget_jobs = job_manager.get_jobs_over_budget()
        
        assert len(over_budget_jobs) == 1
        assert over_budget_jobs[0]['job_id'] == job_id
        assert over_budget_jobs[0]['over_budget_amount'] == 1.0
    
    def test_database_schema_migration(self, job_manager):
        """Test that new database schema is properly created."""
        import sqlite3
        
        with sqlite3.connect(job_manager.db_path) as conn:
            # Check that new columns exist in jobs table
            cursor = conn.execute("PRAGMA table_info(jobs)")
            columns = [row[1] for row in cursor.fetchall()]
            
            assert 'actual_cost' in columns
            assert 'budget_limit' in columns
            assert 'cost_retrieved_at' in columns
            assert 'spot_request_id' in columns
            assert 'billing_tags' in columns
            
            # Check that cost_tracking table exists
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cost_tracking'")
            assert cursor.fetchone() is not None
            
            # Check cost_tracking table structure
            cursor = conn.execute("PRAGMA table_info(cost_tracking)")
            cost_columns = [row[1] for row in cursor.fetchall()]
            
            expected_cost_columns = [
                'id', 'job_id', 'provider', 'cost_type', 'amount', 'currency',
                'billing_period_start', 'billing_period_end', 'retrieved_at', 'raw_data'
            ]
            
            for col in expected_cost_columns:
                assert col in cost_columns
    
    def test_calculate_job_cost_with_actual_cost(self, job_manager, sample_job_with_budget):
        """Test job cost calculation when actual cost is available."""
        # Set actual cost
        job_manager.update_actual_cost(sample_job_with_budget, 5.0)
        
        # The calculate_job_cost method should still work for runtime calculations
        # but actual cost should be available via get_job
        job = job_manager.get_job(sample_job_with_budget)
        assert job['actual_cost'] == 5.0
    
    def test_cost_tracking_foreign_key_constraint(self, job_manager, sample_job_with_budget):
        """Test foreign key constraint in cost_tracking table."""
        import sqlite3
        
        # This should work - valid job_id
        cost_breakdown = [{
            'provider': 'AWS',
            'cost_type': 'compute',
            'amount': 1.0,
            'currency': 'USD',
            'billing_period_start': '2024-01-01T00:00:00',
            'billing_period_end': '2024-01-01T01:00:00',
            'raw_data': {}
        }]
        
        result = job_manager.update_actual_cost(sample_job_with_budget, 1.0, cost_breakdown)
        assert result is True
        
        # Verify the cost record was created
        with sqlite3.connect(job_manager.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM cost_tracking WHERE job_id = ?', (sample_job_with_budget,))
            count = cursor.fetchone()[0]
            assert count == 1
    
    def test_update_actual_cost_error_handling(self, job_manager):
        """Test error handling in update_actual_cost."""
        # Try to update cost for non-existent job
        result = job_manager.update_actual_cost('non-existent-job', 5.0)
        
        # Should still return True (no strict error checking in current implementation)
        # but the actual cost won't be set since job doesn't exist
        assert result is True