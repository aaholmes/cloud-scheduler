#!/usr/bin/env python3
"""
Job Management System for Cloud Scheduler
Provides centralized tracking and control of cloud jobs.
"""
import json
import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JobManager:
    """Manages job state and provides job control operations."""
    
    def __init__(self, db_path: str = "cloud_jobs.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the job tracking database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    instance_type TEXT NOT NULL,
                    instance_id TEXT,
                    region TEXT NOT NULL,
                    public_ip TEXT,
                    private_ip TEXT,
                    s3_bucket TEXT,
                    s3_input_path TEXT,
                    gdrive_path TEXT,
                    basis_set TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    price_per_hour REAL,
                    estimated_cost REAL,
                    actual_cost REAL,
                    budget_limit REAL,
                    cost_retrieved_at TEXT,
                    spot_request_id TEXT,
                    billing_tags TEXT,
                    metadata TEXT
                )
            ''')
            
            # Create cost_tracking table for detailed cost breakdowns
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cost_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    cost_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    billing_period_start TEXT NOT NULL,
                    billing_period_end TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    raw_data TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_cost_tracking_job_id ON cost_tracking(job_id)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_cost_tracking_retrieved_at ON cost_tracking(retrieved_at)
            ''')
    
    def create_job(self, job_id: str, job_config: Dict[str, Any], 
                   launch_result: Dict[str, Any]) -> bool:
        """Create a new job record."""
        try:
            now = datetime.now().isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO jobs (
                        job_id, status, provider, instance_type, instance_id,
                        region, public_ip, private_ip, s3_bucket, s3_input_path,
                        gdrive_path, basis_set, created_at, updated_at,
                        price_per_hour, budget_limit, spot_request_id, billing_tags, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    job_id,
                    launch_result.get('status', 'unknown'),
                    launch_result.get('provider', ''),
                    launch_result.get('instance_type', ''),
                    launch_result.get('instance_id', ''),
                    launch_result.get('region', ''),
                    launch_result.get('public_ip', ''),
                    launch_result.get('private_ip', ''),
                    job_config.get('s3_bucket', ''),
                    job_config.get('s3_input_path', ''),
                    job_config.get('gdrive_path', ''),
                    job_config.get('basis_set', ''),
                    now,
                    now,
                    job_config.get('price_per_hour', 0.0),
                    job_config.get('budget_limit'),
                    launch_result.get('spot_request_id', ''),
                    json.dumps(job_config.get('billing_tags', {})),
                    json.dumps({
                        'launch_result': launch_result,
                        'job_config': job_config
                    })
                ))
            
            logger.info(f"Created job record: {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create job {job_id}: {e}")
            return False
    
    def update_job_status(self, job_id: str, status: str, 
                         additional_data: Optional[Dict[str, Any]] = None) -> bool:
        """Update job status and optional additional data."""
        try:
            now = datetime.now().isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                # Update basic status
                conn.execute('''
                    UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?
                ''', (status, now, job_id))
                
                # Update specific status timestamps
                if status == 'running':
                    conn.execute('''
                        UPDATE jobs SET started_at = ? WHERE job_id = ?
                    ''', (now, job_id))
                elif status in ['completed', 'failed', 'terminated']:
                    conn.execute('''
                        UPDATE jobs SET completed_at = ? WHERE job_id = ?
                    ''', (now, job_id))
                
                # Update additional data if provided
                if additional_data:
                    for key, value in additional_data.items():
                        if key in ['public_ip', 'private_ip', 'instance_id']:
                            conn.execute(f'''
                                UPDATE jobs SET {key} = ? WHERE job_id = ?
                            ''', (value, job_id))
            
            logger.info(f"Updated job {job_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update job {job_id}: {e}")
            return False
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job details by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM jobs WHERE job_id = ?
                ''', (job_id,))
                
                row = cursor.fetchone()
                if row:
                    job = dict(row)
                    # Parse metadata JSON
                    if job['metadata']:
                        job['metadata'] = json.loads(job['metadata'])
                    return job
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None
    
    def list_jobs(self, status: Optional[str] = None, 
                  limit: int = 50) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by status."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if status:
                    cursor = conn.execute('''
                        SELECT * FROM jobs WHERE status = ? 
                        ORDER BY created_at DESC LIMIT ?
                    ''', (status, limit))
                else:
                    cursor = conn.execute('''
                        SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?
                    ''', (limit,))
                
                jobs = []
                for row in cursor.fetchall():
                    job = dict(row)
                    # Parse metadata JSON for summary
                    if job['metadata']:
                        try:
                            job['metadata'] = json.loads(job['metadata'])
                        except:
                            job['metadata'] = {}
                    jobs.append(job)
                
                return jobs
                
        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []
    
    def calculate_job_cost(self, job_id: str) -> float:
        """Calculate current cost of a running job."""
        job = self.get_job(job_id)
        if not job or not job['price_per_hour']:
            return 0.0
        
        start_time = job.get('started_at') or job['created_at']
        end_time = job.get('completed_at') or datetime.now().isoformat()
        
        try:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)
            hours = (end - start).total_seconds() / 3600
            return hours * job['price_per_hour']
        except:
            return 0.0
    
    def cleanup_completed_jobs(self, days_old: int = 30) -> int:
        """Remove job records older than specified days."""
        try:
            cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_date = cutoff_date.replace(day=cutoff_date.day - days_old)
            cutoff_str = cutoff_date.isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    DELETE FROM jobs 
                    WHERE status IN ('completed', 'failed', 'terminated') 
                    AND created_at < ?
                ''', (cutoff_str,))
                
                deleted_count = cursor.rowcount
                logger.info(f"Cleaned up {deleted_count} old job records")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup jobs: {e}")
            return 0
    
    def update_actual_cost(self, job_id: str, actual_cost: float, cost_breakdown: List[Dict[str, Any]] = None) -> bool:
        """Update the actual cost of a completed job."""
        try:
            now = datetime.now().isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                # Update main job record
                conn.execute('''
                    UPDATE jobs SET actual_cost = ?, cost_retrieved_at = ?, updated_at = ?
                    WHERE job_id = ?
                ''', (actual_cost, now, now, job_id))
                
                # Insert detailed cost breakdown if provided
                if cost_breakdown:
                    for cost_item in cost_breakdown:
                        conn.execute('''
                            INSERT INTO cost_tracking (
                                job_id, provider, cost_type, amount, currency,
                                billing_period_start, billing_period_end, retrieved_at, raw_data
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            job_id,
                            cost_item.get('provider', ''),
                            cost_item.get('cost_type', 'compute'),
                            cost_item.get('amount', 0.0),
                            cost_item.get('currency', 'USD'),
                            cost_item.get('billing_period_start', ''),
                            cost_item.get('billing_period_end', ''),
                            now,
                            json.dumps(cost_item.get('raw_data', {}))
                        ))
            
            logger.info(f"Updated actual cost for job {job_id}: ${actual_cost:.4f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update actual cost for job {job_id}: {e}")
            return False
    
    def check_budget_limit(self, job_id: str, estimated_cost: float) -> Dict[str, Any]:
        """Check if estimated cost exceeds budget limit."""
        job = self.get_job(job_id)
        if not job or not job.get('budget_limit'):
            return {'within_budget': True, 'budget_limit': None, 'estimated_cost': estimated_cost}
        
        budget_limit = job['budget_limit']
        within_budget = estimated_cost <= budget_limit
        
        return {
            'within_budget': within_budget,
            'budget_limit': budget_limit,
            'estimated_cost': estimated_cost,
            'budget_usage_percent': (estimated_cost / budget_limit) * 100 if budget_limit > 0 else 0,
            'over_budget_amount': max(0, estimated_cost - budget_limit)
        }
    
    def get_cost_summary(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive cost summary for a job."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Get job details
                job_cursor = conn.execute('''
                    SELECT * FROM jobs WHERE job_id = ?
                ''', (job_id,))
                job = job_cursor.fetchone()
                
                if not job:
                    return None
                
                job_dict = dict(job)
                
                # Get detailed cost breakdown
                cost_cursor = conn.execute('''
                    SELECT * FROM cost_tracking WHERE job_id = ? 
                    ORDER BY billing_period_start DESC
                ''', (job_id,))
                cost_breakdown = [dict(row) for row in cost_cursor.fetchall()]
                
                # Calculate runtime cost if job is running
                current_runtime_cost = self.calculate_job_cost(job_id)
                
                summary = {
                    'job_id': job_id,
                    'provider': job_dict['provider'],
                    'instance_type': job_dict['instance_type'],
                    'status': job_dict['status'],
                    'estimated_cost': job_dict.get('estimated_cost', 0.0),
                    'actual_cost': job_dict.get('actual_cost'),
                    'current_runtime_cost': current_runtime_cost,
                    'budget_limit': job_dict.get('budget_limit'),
                    'cost_retrieved_at': job_dict.get('cost_retrieved_at'),
                    'cost_breakdown': cost_breakdown,
                    'within_budget': True
                }
                
                # Check budget status
                if job_dict.get('budget_limit'):
                    cost_to_check = job_dict.get('actual_cost') or current_runtime_cost
                    budget_check = self.check_budget_limit(job_id, cost_to_check)
                    summary.update(budget_check)
                
                return summary
            
        except Exception as e:
            logger.error(f"Failed to get cost summary for job {job_id}: {e}")
            return None
    
    def get_jobs_over_budget(self) -> List[Dict[str, Any]]:
        """Get all jobs that have exceeded their budget limits."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                cursor = conn.execute('''
                    SELECT job_id, provider, instance_type, status, budget_limit, 
                           actual_cost, estimated_cost, created_at
                    FROM jobs 
                    WHERE budget_limit IS NOT NULL 
                    AND (
                        (actual_cost IS NOT NULL AND actual_cost > budget_limit) OR
                        (actual_cost IS NULL AND estimated_cost IS NOT NULL AND estimated_cost > budget_limit)
                    )
                    ORDER BY created_at DESC
                ''')
                
                over_budget_jobs = []
                for row in cursor.fetchall():
                    job_dict = dict(row)
                    cost_to_check = job_dict.get('actual_cost') or job_dict.get('estimated_cost', 0.0)
                    
                    if cost_to_check > job_dict['budget_limit']:
                        job_dict['over_budget_amount'] = cost_to_check - job_dict['budget_limit']
                        job_dict['budget_usage_percent'] = (cost_to_check / job_dict['budget_limit']) * 100
                        over_budget_jobs.append(job_dict)
                
                return over_budget_jobs
            
        except Exception as e:
            logger.error(f"Failed to get over-budget jobs: {e}")
            return []


def get_job_manager() -> JobManager:
    """Get a JobManager instance (singleton pattern)."""
    if not hasattr(get_job_manager, '_instance'):
        get_job_manager._instance = JobManager()
    return get_job_manager._instance


if __name__ == "__main__":
    # Test the job manager
    jm = JobManager()
    
    # Test job creation
    test_config = {
        's3_bucket': 'test-bucket',
        'gdrive_path': 'test/path',
        'basis_set': 'aug-cc-pVDZ'
    }
    
    test_launch = {
        'status': 'launched',
        'provider': 'AWS',
        'instance_type': 'r5.4xlarge',
        'region': 'us-east-1',
        'instance_id': 'i-123456789'
    }
    
    job_id = 'test-job-123'
    jm.create_job(job_id, test_config, test_launch)
    
    # Test job retrieval
    job = jm.get_job(job_id)
    print(f"Retrieved job: {job['job_id']} - {job['status']}")
    
    # Test job listing
    jobs = jm.list_jobs()
    print(f"Total jobs: {len(jobs)}")