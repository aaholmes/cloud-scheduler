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
                    metadata TEXT
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at)
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
                        price_per_hour, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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