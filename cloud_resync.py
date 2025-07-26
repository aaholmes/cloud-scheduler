#!/usr/bin/env python3
"""
Manually trigger Google Drive sync for a cloud job.
"""
import argparse
import json
import sys
import subprocess
import logging
from typing import Dict, Any, Optional
from job_manager import get_job_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def trigger_resync_via_ssh(job: Dict[str, Any], sync_command: str) -> Dict[str, Any]:
    """Trigger resync by SSH-ing into the instance."""
    if not job.get('public_ip'):
        return {'status': 'error', 'message': 'No public IP available for SSH'}
    
    if job['provider'] != 'AWS':
        return {'status': 'error', 'message': 'SSH resync only supported for AWS instances currently'}
    
    try:
        # Construct SSH command
        ssh_command = [
            'ssh',
            '-i', f"~/.ssh/{job.get('key_name', 'cloud-scheduler-key')}.pem",
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10',
            f"ec2-user@{job['public_ip']}",
            sync_command
        ]
        
        logger.info(f"Executing SSH command: {' '.join(ssh_command)}")
        
        result = subprocess.run(
            ssh_command,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            return {
                'status': 'success',
                'message': 'Resync triggered successfully',
                'output': result.stdout
            }
        else:
            return {
                'status': 'error',
                'message': f'SSH command failed (exit code {result.returncode})',
                'error': result.stderr
            }
    
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': 'SSH command timed out'}
    except Exception as e:
        return {'status': 'error', 'message': f'SSH error: {str(e)}'}


def trigger_local_resync(job: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger resync using local rclone (if output directory exists locally)."""
    gdrive_path = job.get('gdrive_path')
    if not gdrive_path:
        return {'status': 'error', 'message': 'No Google Drive path configured'}
    
    # Check if we have a local output directory matching this job
    local_output_dir = f"job_{job['job_id']}_output"
    
    import os
    if not os.path.exists(local_output_dir):
        return {
            'status': 'error', 
            'message': f'Local output directory {local_output_dir} not found'
        }
    
    try:
        # Use rclone to sync local directory to Google Drive
        rclone_command = [
            'rclone', 'sync', local_output_dir, f'gdrive:{gdrive_path}',
            '--create-empty-src-dirs',
            '--exclude', 'FCIDUMP',
            '--exclude', '*.tmp',
            '--progress'
        ]
        
        logger.info(f"Executing rclone command: {' '.join(rclone_command)}")
        
        result = subprocess.run(
            rclone_command,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            return {
                'status': 'success',
                'message': 'Local resync completed successfully',
                'output': result.stdout
            }
        else:
            return {
                'status': 'error',
                'message': f'rclone sync failed (exit code {result.returncode})',
                'error': result.stderr
            }
    
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': 'rclone sync timed out'}
    except FileNotFoundError:
        return {'status': 'error', 'message': 'rclone not found - please install rclone'}
    except Exception as e:
        return {'status': 'error', 'message': f'rclone error: {str(e)}'}


def check_gdrive_space() -> Dict[str, Any]:
    """Check Google Drive space and quota."""
    try:
        result = subprocess.run(
            ['rclone', 'about', 'gdrive:'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return {
                'status': 'success',
                'info': result.stdout
            }
        else:
            return {
                'status': 'error',
                'message': 'Could not check Google Drive space',
                'error': result.stderr
            }
    
    except Exception as e:
        return {'status': 'error', 'message': f'Error checking drive space: {str(e)}'}


def main():
    """Main function for cloud_resync.py"""
    parser = argparse.ArgumentParser(description="Manually trigger Google Drive sync for a cloud job")
    parser.add_argument("job_id", help="Job ID to resync")
    parser.add_argument("--method", choices=['ssh', 'local'], default='ssh',
                       help="Resync method (default: ssh)")
    parser.add_argument("--force", action="store_true",
                       help="Force resync even if job appears completed")
    parser.add_argument("--check-space", action="store_true",
                       help="Check Google Drive space before syncing")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be synced without actually syncing")
    
    args = parser.parse_args()
    
    # Get job from database
    jm = get_job_manager()
    job = jm.get_job(args.job_id)
    
    if not job:
        print(f"Job {args.job_id} not found")
        sys.exit(1)
    
    print(f"Job {args.job_id}: {job['status']}")
    print(f"Provider: {job['provider']}")
    print(f"Google Drive path: {job.get('gdrive_path', 'Not configured')}")
    print()
    
    # Check if job is in a state where resync makes sense
    if job['status'] in ['failed', 'terminated'] and not args.force:
        print("Warning: Job appears to be terminated. Use --force to resync anyway.")
        sys.exit(1)
    
    # Check Google Drive space if requested
    if args.check_space:
        print("Checking Google Drive space...")
        space_info = check_gdrive_space()
        if space_info['status'] == 'success':
            print(space_info['info'])
        else:
            print(f"Could not check space: {space_info['message']}")
        print()
    
    # Perform resync based on method
    if args.method == 'ssh':
        print("Triggering resync via SSH...")
        
        # Construct the sync command to run on the remote instance
        gdrive_path = job.get('gdrive_path', 'shci_jobs/unknown')
        sync_command = (
            f'cd $HOME && '
            f'./sync_results.sh shci_output gdrive "{gdrive_path}"'
        )
        
        if args.dry_run:
            sync_command += ' --dry-run'
        
        result = trigger_resync_via_ssh(job, sync_command)
        
    elif args.method == 'local':
        print("Triggering local resync...")
        result = trigger_local_resync(job)
    
    # Display results
    if result['status'] == 'success':
        print("✓ Resync completed successfully")
        if result.get('output'):
            print("Output:")
            print(result['output'])
    else:
        print(f"✗ Resync failed: {result['message']}")
        if result.get('error'):
            print("Error details:")
            print(result['error'])
        sys.exit(1)


if __name__ == "__main__":
    main()