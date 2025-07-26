"""Tests for cloud_cost_report.py"""
import json
import pytest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from io import StringIO

from cloud_cost_report import CostReporter
from job_manager import JobManager


class TestCostReporter:
    """Test CostReporter functionality."""
    
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
    def cost_reporter(self, temp_db):
        """Create CostReporter with mocked dependencies."""
        with patch('cloud_cost_report.get_job_manager') as mock_get_jm:
            with patch('cloud_cost_report.CloudCostTracker') as mock_tracker:
                mock_get_jm.return_value = JobManager(temp_db)
                mock_tracker.return_value = MagicMock()
                reporter = CostReporter()
                return reporter
    
    @pytest.fixture
    def sample_jobs(self, job_manager):
        """Create sample jobs for testing."""
        jobs = []
        
        # Job 1: Completed AWS job within budget
        job_config_1 = {
            's3_bucket': 'test-bucket',
            'budget_limit': 10.0,
            'price_per_hour': 0.5
        }
        launch_result_1 = {
            'status': 'completed',
            'provider': 'AWS',
            'instance_type': 'r5.4xlarge',
            'region': 'us-east-1'
        }
        job_id_1 = 'aws-job-1'
        job_manager.create_job(job_id_1, job_config_1, launch_result_1)
        job_manager.update_job_status(job_id_1, 'completed')
        job_manager.update_actual_cost(job_id_1, 8.0)
        jobs.append(job_id_1)
        
        # Job 2: Completed GCP job over budget
        job_config_2 = {
            's3_bucket': 'test-bucket',
            'budget_limit': 15.0,
            'price_per_hour': 0.8
        }
        launch_result_2 = {
            'status': 'completed',
            'provider': 'GCP',
            'instance_type': 'n2-highmem-16',
            'region': 'us-central1'
        }
        job_id_2 = 'gcp-job-1'
        job_manager.create_job(job_id_2, job_config_2, launch_result_2)
        job_manager.update_job_status(job_id_2, 'completed')
        job_manager.update_actual_cost(job_id_2, 18.0)
        jobs.append(job_id_2)
        
        # Job 3: Running Azure job
        job_config_3 = {
            's3_bucket': 'test-bucket',
            'budget_limit': 20.0,
            'price_per_hour': 1.0
        }
        launch_result_3 = {
            'status': 'running',
            'provider': 'Azure',
            'instance_type': 'Standard_E16s_v5',
            'region': 'eastus'
        }
        job_id_3 = 'azure-job-1'
        job_manager.create_job(job_id_3, job_config_3, launch_result_3)
        job_manager.update_job_status(job_id_3, 'running')
        jobs.append(job_id_3)
        
        return jobs
    
    def test_generate_job_summary(self, cost_reporter, sample_jobs):
        """Test generating job summary."""
        job_id = sample_jobs[0]  # AWS job
        
        summary = cost_reporter.generate_job_summary(job_id)
        
        assert summary is not None
        assert 'error' not in summary
        assert summary['job_id'] == job_id
        assert summary['provider'] == 'AWS'
        assert summary['instance_type'] == 'r5.4xlarge'
        assert summary['actual_cost'] == 8.0
        assert summary['budget_limit'] == 10.0
        assert summary['within_budget'] is True
    
    def test_generate_job_summary_nonexistent(self, cost_reporter):
        """Test generating job summary for non-existent job."""
        summary = cost_reporter.generate_job_summary('nonexistent-job')
        
        assert 'error' in summary
        assert 'not found' in summary['error']
    
    def test_generate_cost_trends(self, cost_reporter, sample_jobs):
        """Test generating cost trends report."""
        trends = cost_reporter.generate_cost_trends(days=30)
        
        assert trends is not None
        assert 'error' not in trends
        assert 'period' in trends
        assert 'totals' in trends
        assert 'provider_breakdown' in trends
        assert 'daily_costs' in trends
        
        # Check totals
        totals = trends['totals']
        assert totals['job_count'] >= 3
        assert totals['total_cost'] >= 26.0  # 8 + 18 + estimated for running job
        
        # Check provider breakdown
        providers = trends['provider_breakdown']
        assert 'AWS' in providers
        assert 'GCP' in providers
        assert providers['AWS']['job_count'] >= 1
        assert providers['GCP']['job_count'] >= 1
    
    def test_generate_cost_trends_with_provider_filter(self, cost_reporter, sample_jobs):
        """Test generating cost trends with provider filter."""
        trends = cost_reporter.generate_cost_trends(days=30, provider='AWS')
        
        assert trends is not None
        assert 'error' not in trends
        
        # Should only include AWS jobs
        provider_breakdown = trends['provider_breakdown']
        assert 'AWS' in provider_breakdown
        assert len([p for p in provider_breakdown.keys() if p != 'AWS']) == 0
    
    def test_generate_budget_analysis(self, cost_reporter, sample_jobs):
        """Test generating budget analysis."""
        analysis = cost_reporter.generate_budget_analysis()
        
        assert analysis is not None
        assert 'error' not in analysis
        assert 'summary' in analysis
        assert 'over_budget_jobs' in analysis
        assert 'recent_budget_jobs' in analysis
        
        summary = analysis['summary']
        assert summary['total_jobs_with_budget'] >= 3
        assert summary['jobs_within_budget'] >= 1
        assert summary['jobs_over_budget'] >= 1
        assert summary['total_budget_allocated'] >= 45.0  # 10 + 15 + 20
        
        # Check that over-budget job is included
        over_budget_jobs = analysis['over_budget_jobs']
        assert len(over_budget_jobs) >= 1
        
        gcp_job = next((job for job in over_budget_jobs if job['job_id'] == 'gcp-job-1'), None)
        assert gcp_job is not None
        assert gcp_job['over_budget_amount'] == 3.0  # 18 - 15
    
    def test_generate_provider_comparison(self, cost_reporter, sample_jobs):
        """Test generating provider comparison."""
        comparison = cost_reporter.generate_provider_comparison(days=30)
        
        assert comparison is not None
        assert 'error' not in comparison
        assert 'period' in comparison
        assert 'provider_stats' in comparison
        assert 'recommendations' in comparison
        
        provider_stats = comparison['provider_stats']
        assert len(provider_stats) >= 2  # At least AWS and GCP
        
        # Check that stats are calculated
        for stats in provider_stats:
            assert 'provider' in stats
            assert 'job_count' in stats
            assert 'total_cost' in stats
            assert 'avg_cost' in stats
            assert 'success_rate' in stats
        
        # Check recommendations
        recommendations = comparison['recommendations']
        assert 'cheapest_provider' in recommendations
        assert 'most_reliable_provider' in recommendations
        assert 'most_used_provider' in recommendations
    
    def test_print_job_summary(self, cost_reporter, sample_jobs):
        """Test printing job summary."""
        job_id = sample_jobs[0]  # AWS job
        
        # Capture printed output
        with patch('builtins.print') as mock_print:
            cost_reporter.print_job_summary(job_id)
        
        # Verify print was called
        mock_print.assert_called()
        
        # Check that job information was included in output
        printed_text = ' '.join([str(call.args[0]) for call in mock_print.call_args_list])
        assert job_id in printed_text
        assert 'AWS' in printed_text
        assert 'r5.4xlarge' in printed_text
        assert '$8.0000' in printed_text or '8.0' in printed_text
    
    def test_print_job_summary_error(self, cost_reporter):
        """Test printing job summary for non-existent job."""
        with patch('builtins.print') as mock_print:
            cost_reporter.print_job_summary('nonexistent-job')
        
        # Should print error message
        mock_print.assert_called()
        printed_text = str(mock_print.call_args_list[0].args[0])
        assert 'Error:' in printed_text
    
    def test_print_cost_trends(self, cost_reporter, sample_jobs):
        """Test printing cost trends."""
        with patch('builtins.print') as mock_print:
            cost_reporter.print_cost_trends(days=30)
        
        mock_print.assert_called()
        
        # Check that trend information was included
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list]
        printed_text = ' '.join(printed_lines)
        
        assert 'COST TRENDS REPORT' in printed_text
        assert 'Total Jobs:' in printed_text
        assert 'Total Cost:' in printed_text
    
    def test_print_budget_analysis(self, cost_reporter, sample_jobs):
        """Test printing budget analysis."""
        with patch('builtins.print') as mock_print:
            cost_reporter.print_budget_analysis()
        
        mock_print.assert_called()
        
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list]
        printed_text = ' '.join(printed_lines)
        
        assert 'BUDGET ANALYSIS REPORT' in printed_text
        assert 'Total Jobs with Budget:' in printed_text
        assert 'Jobs Within Budget:' in printed_text
        assert 'Jobs Over Budget:' in printed_text
    
    def test_print_provider_comparison(self, cost_reporter, sample_jobs):
        """Test printing provider comparison."""
        with patch('builtins.print') as mock_print:
            cost_reporter.print_provider_comparison(days=30)
        
        mock_print.assert_called()
        
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list]
        printed_text = ' '.join(printed_lines)
        
        assert 'PROVIDER COMPARISON REPORT' in printed_text
        assert 'Provider' in printed_text
        assert 'Jobs' in printed_text
        assert 'Total Cost' in printed_text
        assert 'Recommendations' in printed_text
    
    def test_generate_job_summary_with_cost_accuracy(self, cost_reporter, job_manager):
        """Test generating job summary with cost accuracy analysis."""
        # Create job with both estimated and actual cost
        job_config = {
            's3_bucket': 'test-bucket',
            'estimated_cost': 5.0,
            'price_per_hour': 1.0
        }
        launch_result = {
            'status': 'completed',
            'provider': 'AWS',
            'instance_type': 'r5.large',
            'region': 'us-east-1'
        }
        job_id = 'accuracy-test-job'
        
        job_manager.create_job(job_id, job_config, launch_result)
        job_manager.update_job_status(job_id, 'completed')
        
        # Set estimated cost manually in database
        import sqlite3
        with sqlite3.connect(job_manager.db_path) as conn:
            conn.execute('UPDATE jobs SET estimated_cost = ? WHERE job_id = ?', (5.0, job_id))
        
        # Update actual cost
        job_manager.update_actual_cost(job_id, 4.5)
        
        summary = cost_reporter.generate_job_summary(job_id)
        
        assert 'cost_accuracy' in summary
        accuracy = summary['cost_accuracy']
        assert accuracy['estimated'] == 5.0
        assert accuracy['actual'] == 4.5
        assert accuracy['difference'] == -0.5
        assert accuracy['accuracy_percent'] == 90.0  # 1 - 0.5/5.0 = 0.9
    
    def test_database_error_handling(self, cost_reporter):
        """Test error handling when database operations fail."""
        # Mock database connection to raise an exception
        with patch('sqlite3.connect') as mock_connect:
            mock_connect.side_effect = Exception("Database error")
            
            trends = cost_reporter.generate_cost_trends()
            assert 'error' in trends
            assert 'Database error' in trends['error']
            
            analysis = cost_reporter.generate_budget_analysis()
            assert 'error' in analysis
            
            comparison = cost_reporter.generate_provider_comparison()
            assert 'error' in comparison
    
    def test_empty_database(self, cost_reporter):
        """Test reports with empty database."""
        trends = cost_reporter.generate_cost_trends()
        
        assert trends is not None
        assert trends['totals']['job_count'] == 0
        assert trends['totals']['total_cost'] == 0
        assert len(trends['provider_breakdown']) == 0
        assert len(trends['daily_costs']) == 0
        
        analysis = cost_reporter.generate_budget_analysis()
        assert analysis['summary']['total_jobs_with_budget'] == 0
        assert len(analysis['over_budget_jobs']) == 0
        
        comparison = cost_reporter.generate_provider_comparison()
        assert len(comparison['provider_stats']) == 0
        assert comparison['recommendations']['cheapest_provider'] is None