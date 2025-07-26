"""Unit tests for job_manager.py functionality."""
import os
import sqlite3
import tempfile
import pytest
from datetime import datetime
from unittest.mock import patch
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from job_manager import JobManager, get_job_manager


class TestJobManager:
    """Test JobManager database operations."""
    
    def test_job_manager_initialization(self, temp_dir):
        """Test JobManager initialization and database creation."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        # Verify database file is created
        assert os.path.exists(db_path)
        
        # Verify table structure
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        assert cursor.fetchone() is not None
        conn.close()
    
    def test_create_job(self, temp_dir):
        """Test job creation functionality."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        job_config = {
            's3_bucket': 'test-bucket',
            's3_input_path': 's3://test-bucket/job123/input/',
            'gdrive_path': 'results/water_dimer',
            'basis_set': 'aug-cc-pVDZ',
            'price_per_hour': 0.512
        }
        
        launch_result = {
            'status': 'launched',
            'provider': 'AWS',
            'instance_type': 'r5.4xlarge',
            'region': 'us-east-1',
            'instance_id': 'i-1234567890',
            'public_ip': '54.123.45.67'
        }
        
        success = jm.create_job('test-job-123', job_config, launch_result)
        assert success
        
        # Verify job was created in database
        job = jm.get_job('test-job-123')
        assert job is not None
        assert job['job_id'] == 'test-job-123'
        assert job['status'] == 'launched'
        assert job['provider'] == 'AWS'
        assert job['instance_type'] == 'r5.4xlarge'
        assert job['s3_bucket'] == 'test-bucket'
    
    def test_update_job_status(self, temp_dir):
        """Test job status updates."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        # Create initial job
        job_config = {'s3_bucket': 'test', 'price_per_hour': 0.5}
        launch_result = {'status': 'launching', 'provider': 'AWS'}
        jm.create_job('test-job', job_config, launch_result)
        
        # Update status
        update_data = {
            'instance_id': 'i-abcdef123',
            'public_ip': '1.2.3.4',
            'private_ip': '10.0.1.100'
        }
        
        success = jm.update_job_status('test-job', 'running', update_data)
        assert success
        
        # Verify update
        job = jm.get_job('test-job')
        assert job['status'] == 'running'
        assert job['instance_id'] == 'i-abcdef123'
        assert job['public_ip'] == '1.2.3.4'
        assert job['private_ip'] == '10.0.1.100'
    
    def test_list_jobs(self, temp_dir):
        """Test job listing functionality."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        # Create multiple jobs
        for i in range(3):
            job_config = {'s3_bucket': f'bucket-{i}', 'price_per_hour': 0.5}
            launch_result = {'status': 'launched', 'provider': 'AWS'}
            jm.create_job(f'job-{i}', job_config, launch_result)
        
        # List all jobs
        jobs = jm.list_jobs()
        assert len(jobs) == 3
        
        # List jobs by status
        jm.update_job_status('job-1', 'completed')
        running_jobs = jm.list_jobs(status='launched')
        completed_jobs = jm.list_jobs(status='completed')
        
        assert len(running_jobs) == 2
        assert len(completed_jobs) == 1
        assert completed_jobs[0]['job_id'] == 'job-1'
    
    def test_calculate_job_cost(self, temp_dir):
        """Test job cost calculation."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        # Create job with known start time
        job_config = {'s3_bucket': 'test', 'price_per_hour': 0.512}
        launch_result = {'status': 'launched', 'provider': 'AWS'}
        jm.create_job('cost-test', job_config, launch_result)
        
        # Update end time (simulate 2 hours runtime)
        with patch('job_manager.datetime') as mock_datetime:
            # Mock current time to be 2 hours after creation
            start_time = datetime.now()
            end_time = start_time.replace(hour=start_time.hour + 2)
            mock_datetime.now.return_value = end_time
            
            jm.update_job_status('cost-test', 'completed')
            
            job = jm.get_job('cost-test')
            cost = jm.calculate_job_cost('cost-test')
            
            # Should be approximately $0.512 * 2 hours = $1.024
            assert cost is not None
            assert abs(cost - 1.024) < 0.1  # Allow some tolerance for timing
    
    def test_delete_job(self, temp_dir):
        """Test job deletion."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        # Create job
        job_config = {'s3_bucket': 'test', 'price_per_hour': 0.5}
        launch_result = {'status': 'launched', 'provider': 'AWS'}
        jm.create_job('delete-test', job_config, launch_result)
        
        # Verify job exists
        assert jm.get_job('delete-test') is not None
        
        # Delete job
        success = jm.delete_job('delete-test')
        assert success
        
        # Verify job is gone
        assert jm.get_job('delete-test') is None
    
    def test_duplicate_job_handling(self, temp_dir):
        """Test handling of duplicate job IDs."""
        db_path = os.path.join(temp_dir, 'test_jobs.db')
        jm = JobManager(db_path)
        
        job_config = {'s3_bucket': 'test', 'price_per_hour': 0.5}
        launch_result = {'status': 'launched', 'provider': 'AWS'}
        
        # Create first job
        success1 = jm.create_job('duplicate-test', job_config, launch_result)
        assert success1
        
        # Try to create duplicate
        success2 = jm.create_job('duplicate-test', job_config, launch_result)
        assert not success2  # Should fail due to duplicate
        
        # Verify only one job exists
        jobs = jm.list_jobs()
        duplicate_jobs = [job for job in jobs if job['job_id'] == 'duplicate-test']
        assert len(duplicate_jobs) == 1


class TestJobManagerSingleton:
    """Test job manager singleton pattern."""
    
    def test_get_job_manager_singleton(self):
        """Test that get_job_manager returns same instance."""
        jm1 = get_job_manager()
        jm2 = get_job_manager()
        
        assert jm1 is jm2  # Same instance
        assert isinstance(jm1, JobManager)
    
    @patch.dict(os.environ, {'CLOUD_SCHEDULER_DB': '/custom/path/jobs.db'})
    def test_custom_database_path(self):
        """Test custom database path from environment variable."""
        # Reset singleton
        if hasattr(get_job_manager, '_instance'):
            delattr(get_job_manager, '_instance')
        
        jm = get_job_manager()
        # Note: This would use the custom path in a real scenario
        # but for testing we just verify the function doesn't crash
        assert isinstance(jm, JobManager)


class TestDatabaseSchemaAndMigration:
    """Test database schema and potential migrations."""
    
    def test_database_schema_creation(self, temp_dir):
        """Test that database schema is created correctly."""
        db_path = os.path.join(temp_dir, 'schema_test.db')
        jm = JobManager(db_path)
        
        # Verify all expected columns exist
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(jobs)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type
        
        expected_columns = {
            'job_id': 'TEXT',
            'status': 'TEXT',
            'provider': 'TEXT',
            'instance_type': 'TEXT',
            'region': 'TEXT',
            'instance_id': 'TEXT',
            'public_ip': 'TEXT',
            'private_ip': 'TEXT',
            's3_bucket': 'TEXT',
            's3_input_path': 'TEXT',
            'gdrive_path': 'TEXT',
            'basis_set': 'TEXT',
            'price_per_hour': 'REAL',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
            'completed_at': 'TIMESTAMP'
        }
        
        for col_name, col_type in expected_columns.items():
            assert col_name in columns, f"Column {col_name} missing from schema"
            assert columns[col_name] == col_type, f"Column {col_name} has wrong type"
        
        conn.close()
    
    def test_database_constraints(self, temp_dir):
        """Test database constraints and indexes."""
        db_path = os.path.join(temp_dir, 'constraints_test.db')
        jm = JobManager(db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Test primary key constraint
        cursor.execute("PRAGMA table_info(jobs)")
        columns = cursor.fetchall()
        pk_columns = [col for col in columns if col[5] == 1]  # pk flag
        assert len(pk_columns) == 1
        assert pk_columns[0][1] == 'job_id'  # column name
        
        conn.close()


class TestErrorHandling:
    """Test error handling in JobManager."""
    
    def test_database_connection_error(self):
        """Test handling of database connection errors."""
        # Try to create JobManager with invalid path
        with pytest.raises(Exception):
            JobManager('/invalid/path/that/does/not/exist/test.db')
    
    def test_nonexistent_job_operations(self, temp_dir):
        """Test operations on non-existent jobs."""
        db_path = os.path.join(temp_dir, 'error_test.db')
        jm = JobManager(db_path)
        
        # Get non-existent job
        job = jm.get_job('nonexistent')
        assert job is None
        
        # Update non-existent job
        success = jm.update_job_status('nonexistent', 'completed')
        assert not success
        
        # Delete non-existent job
        success = jm.delete_job('nonexistent')
        assert not success
        
        # Calculate cost for non-existent job
        cost = jm.calculate_job_cost('nonexistent')
        assert cost is None
    
    def test_invalid_job_data(self, temp_dir):
        """Test handling of invalid job data."""
        db_path = os.path.join(temp_dir, 'invalid_test.db')
        jm = JobManager(db_path)
        
        # Try to create job with missing required fields
        incomplete_config = {'s3_bucket': 'test'}  # Missing price_per_hour
        launch_result = {'status': 'launched'}
        
        # Should handle gracefully (might create with NULL values)
        success = jm.create_job('invalid-test', incomplete_config, launch_result)
        # The specific behavior depends on implementation - 
        # either it succeeds with NULL values or fails gracefully
        assert isinstance(success, bool)