#!/usr/bin/env python3
"""
Update Job Completion - Handles job completion tasks including cost retrieval.
This script is called when a job completes on the cloud instance.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add the project directory to Python path for imports
sys.path.insert(0, '/opt/cloud-scheduler')

try:
    from job_manager import get_job_manager
    from cost_tracker import CloudCostTracker
except ImportError as e:
    # Fallback if running on cloud instance without full codebase
    logging.warning(f"Import error: {e}. Running in minimal mode.")
    get_job_manager = None
    CloudCostTracker = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_completion_metadata(job_id: str, output_dir: str) -> Dict[str, Any]:
    """Create metadata about job completion."""
    metadata = {
        'job_id': job_id,
        'completed_at': datetime.now().isoformat(),
        'output_directory': output_dir,
        'instance_metadata': get_instance_metadata()
    }
    
    # Check for calculation results
    output_path = Path(output_dir)
    if output_path.exists():
        # Count output files
        output_files = list(output_path.glob('*'))
        metadata['output_files_count'] = len(output_files)
        metadata['output_size_mb'] = sum(f.stat().st_size for f in output_files if f.is_file()) / (1024 * 1024)
        
        # Check for specific result files
        result_files = {
            'calculation_log': (output_path / 'calculation.log').exists(),
            'calculation_summary': (output_path / 'calculation_summary.json').exists(),
            'shci_output': (output_path / 'shci.out').exists(),
            'fcidump': (output_path / 'FCIDUMP').exists()
        }
        metadata['result_files'] = result_files
        
        # Check if calculation was successful
        log_file = output_path / 'calculation.log'
        if log_file.exists():
            try:
                with open(log_file, 'r') as f:
                    log_content = f.read()
                    if 'Calculation completed successfully' in log_content:
                        metadata['calculation_status'] = 'success'
                    elif 'error' in log_content.lower() or 'failed' in log_content.lower():
                        metadata['calculation_status'] = 'failed'
                    else:
                        metadata['calculation_status'] = 'unknown'
            except Exception as e:
                logger.warning(f"Could not read calculation log: {e}")
                metadata['calculation_status'] = 'unknown'
    
    return metadata


def get_instance_metadata() -> Dict[str, Any]:
    """Get cloud instance metadata."""
    metadata = {}
    
    try:
        # Try to determine cloud provider and get metadata
        if os.path.exists('/sys/hypervisor/uuid'):
            with open('/sys/hypervisor/uuid', 'r') as f:
                if f.read().startswith('ec2'):
                    metadata['provider'] = 'AWS'
                    metadata.update(get_aws_metadata())
        elif os.system('curl -s -f -m 1 http://metadata.google.internal > /dev/null 2>&1') == 0:
            metadata['provider'] = 'GCP'
            metadata.update(get_gcp_metadata())
        elif os.system('curl -s -f -m 1 -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" > /dev/null 2>&1') == 0:
            metadata['provider'] = 'Azure'
            metadata.update(get_azure_metadata())
    except Exception as e:
        logger.warning(f"Could not retrieve instance metadata: {e}")
    
    return metadata


def get_aws_metadata() -> Dict[str, Any]:
    """Get AWS instance metadata."""
    import urllib.request
    
    metadata = {}
    base_url = 'http://169.254.169.254/latest/meta-data/'
    
    try:
        # Get instance ID
        response = urllib.request.urlopen(f"{base_url}instance-id", timeout=5)
        metadata['instance_id'] = response.read().decode()
        
        # Get instance type
        response = urllib.request.urlopen(f"{base_url}instance-type", timeout=5)
        metadata['instance_type'] = response.read().decode()
        
        # Get region
        response = urllib.request.urlopen(f"{base_url}placement/region", timeout=5)
        metadata['region'] = response.read().decode()
        
        # Get spot instance request ID if available
        try:
            response = urllib.request.urlopen(f"{base_url}spot/instance-action", timeout=5)
            metadata['spot_instance'] = True
        except:
            metadata['spot_instance'] = False
            
    except Exception as e:
        logger.warning(f"Failed to get AWS metadata: {e}")
    
    return metadata


def get_gcp_metadata() -> Dict[str, Any]:
    """Get GCP instance metadata."""
    import urllib.request
    
    metadata = {}
    base_url = 'http://metadata.google.internal/computeMetadata/v1/instance/'
    headers = {'Metadata-Flavor': 'Google'}
    
    try:
        # Get instance name
        req = urllib.request.Request(f"{base_url}name", headers=headers)
        response = urllib.request.urlopen(req, timeout=5)
        metadata['instance_name'] = response.read().decode()
        
        # Get machine type
        req = urllib.request.Request(f"{base_url}machine-type", headers=headers)
        response = urllib.request.urlopen(req, timeout=5)
        machine_type_url = response.read().decode()
        metadata['instance_type'] = machine_type_url.split('/')[-1]
        
        # Get zone
        req = urllib.request.Request(f"{base_url}zone", headers=headers)
        response = urllib.request.urlopen(req, timeout=5)
        zone_url = response.read().decode()
        metadata['zone'] = zone_url.split('/')[-1]
        
        # Check if preemptible
        try:
            req = urllib.request.Request(f"{base_url}scheduling/preemptible", headers=headers)
            response = urllib.request.urlopen(req, timeout=5)
            metadata['preemptible'] = response.read().decode().lower() == 'true'
        except:
            metadata['preemptible'] = False
            
    except Exception as e:
        logger.warning(f"Failed to get GCP metadata: {e}")
    
    return metadata


def get_azure_metadata() -> Dict[str, Any]:
    """Get Azure instance metadata."""
    import urllib.request
    import json
    
    metadata = {}
    url = 'http://169.254.169.254/metadata/instance?api-version=2021-02-01'
    headers = {'Metadata': 'true'}
    
    try:
        req = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(req, timeout=5)
        instance_data = json.loads(response.read().decode())
        
        compute = instance_data.get('compute', {})
        metadata['vm_name'] = compute.get('name')
        metadata['instance_type'] = compute.get('vmSize')
        metadata['region'] = compute.get('location')
        metadata['resource_group'] = compute.get('resourceGroupName')
        
        # Check if spot instance
        metadata['spot_instance'] = compute.get('priority') == 'Spot'
        
    except Exception as e:
        logger.warning(f"Failed to get Azure metadata: {e}")
    
    return metadata


def notify_job_completion(job_id: str, status: str, completion_metadata: Dict[str, Any]):
    """Notify the job management system about completion."""
    if not get_job_manager:
        logger.warning("Job manager not available. Skipping database update.")
        return
    
    try:
        jm = get_job_manager()
        
        # Update job status
        success = jm.update_job_status(job_id, status, {
            'completion_metadata': completion_metadata
        })
        
        if success:
            logger.info(f"Updated job {job_id} status to {status}")
            
            # Trigger cost retrieval asynchronously (after a delay to allow billing data to update)
            if CloudCostTracker and status == 'completed':
                logger.info(f"Scheduling cost retrieval for job {job_id}")
                try:
                    import shlex
                    import subprocess
                    import tempfile
                    
                    # Sanitize job_id for safe usage
                    safe_job_id = shlex.quote(job_id)
                    
                    # Create a simple script to run cost retrieval later
                    cost_script = f"""#!/bin/bash
# Wait for billing data to be available (typically 24-48 hours)
sleep 3600  # Wait 1 hour initially

# Try to retrieve costs with retries
python3 -c "
import sys
sys.path.insert(0, '/opt/cloud-scheduler')
from cost_tracker import CloudCostTracker
tracker = CloudCostTracker()
for attempt in range(5):
    if tracker.retrieve_job_cost({safe_job_id}):
        break
    import time
    time.sleep(86400)  # Wait 24 hours between attempts
"
"""
                    
                    # Use secure temporary file handling
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                        f.write(cost_script)
                        script_path = f.name
                    
                    os.chmod(script_path, 0o755)
                    
                    # Use safe subprocess execution
                    log_path = f'/tmp/cost_retrieval_{shlex.quote(job_id)}.log'
                    with open(log_path, 'w') as log_file:
                        subprocess.Popen(['nohup', script_path], 
                                       stdout=log_file, 
                                       stderr=subprocess.STDOUT)
                    
                    logger.info(f"Cost retrieval scheduled for job {job_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to schedule cost retrieval for job {job_id}: {e}")
        else:
            logger.error(f"Failed to update job {job_id} status")
            
    except Exception as e:
        logger.error(f"Failed to notify job completion for {job_id}: {e}")


def save_completion_file(output_dir: str, completion_metadata: Dict[str, Any]):
    """Save completion metadata to output directory."""
    try:
        completion_file = Path(output_dir) / 'job_completion.json'
        with open(completion_file, 'w') as f:
            json.dump(completion_metadata, f, indent=2)
        
        logger.info(f"Saved completion metadata to {completion_file}")
        
    except Exception as e:
        logger.error(f"Failed to save completion metadata: {e}")


def main():
    """Main function for job completion handling."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Handle job completion tasks")
    parser.add_argument("--job-id", required=True, help="Job ID")
    parser.add_argument("--output-dir", required=True, help="Output directory path")
    parser.add_argument("--status", default="completed", choices=['completed', 'failed', 'terminated'],
                       help="Job completion status")
    
    args = parser.parse_args()
    
    logger.info(f"Processing job completion: {args.job_id}")
    
    # Create completion metadata
    completion_metadata = create_completion_metadata(args.job_id, args.output_dir)
    logger.info(f"Completion metadata: {json.dumps(completion_metadata, indent=2)}")
    
    # Save completion file
    save_completion_file(args.output_dir, completion_metadata)
    
    # Notify job management system
    notify_job_completion(args.job_id, args.status, completion_metadata)
    
    logger.info(f"Job completion processing finished for {args.job_id}")


if __name__ == "__main__":
    main()