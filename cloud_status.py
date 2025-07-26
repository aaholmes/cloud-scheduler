#!/usr/bin/env python3
"""
Check the status of a running cloud job.
"""
import argparse
import json
import sys
import boto3
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from job_manager import get_job_manager
from google.cloud import compute_v1
from azure.mgmt.compute import ComputeManagementClient
from azure.identity import DefaultAzureCredential

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_aws_instance_status(instance_id: str, region: str) -> Dict[str, Any]:
    """Check AWS instance status."""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        if not response['Reservations']:
            return {'status': 'not_found', 'state': 'terminated'}
        
        instance = response['Reservations'][0]['Instances'][0]
        
        return {
            'status': 'found',
            'state': instance['State']['Name'],
            'public_ip': instance.get('PublicIpAddress'),
            'private_ip': instance.get('PrivateIpAddress'),
            'launch_time': instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else '',
            'instance_type': instance.get('InstanceType'),
            'availability_zone': instance.get('Placement', {}).get('AvailabilityZone'),
            'spot_instance_request_id': instance.get('SpotInstanceRequestId')
        }
        
    except Exception as e:
        logger.error(f"Failed to check AWS instance {instance_id}: {e}")
        return {'status': 'error', 'error': str(e)}


def check_gcp_instance_status(instance_name: str, project_id: str, zone: str) -> Dict[str, Any]:
    """Check GCP instance status."""
    try:
        compute_client = compute_v1.InstancesClient()
        
        instance = compute_client.get(
            project=project_id,
            zone=zone,
            instance=instance_name
        )
        
        # Get external IP
        external_ip = None
        if instance.network_interfaces:
            for interface in instance.network_interfaces:
                if interface.access_configs:
                    external_ip = interface.access_configs[0].nat_i_p
                    break
        
        return {
            'status': 'found',
            'state': instance.status.lower(),
            'public_ip': external_ip,
            'private_ip': instance.network_interfaces[0].network_i_p if instance.network_interfaces else None,
            'creation_timestamp': instance.creation_timestamp,
            'machine_type': instance.machine_type.split('/')[-1],
            'zone': zone,
            'preemptible': instance.scheduling.preemptible if instance.scheduling else False
        }
        
    except Exception as e:
        logger.error(f"Failed to check GCP instance {instance_name}: {e}")
        return {'status': 'error', 'error': str(e)}


def check_azure_instance_status(vm_name: str, resource_group: str, subscription_id: str) -> Dict[str, Any]:
    """Check Azure VM status."""
    try:
        credential = DefaultAzureCredential()
        compute_client = ComputeManagementClient(credential, subscription_id)
        
        vm = compute_client.virtual_machines.get(resource_group, vm_name)
        
        # Get instance view for power state
        instance_view = compute_client.virtual_machines.instance_view(resource_group, vm_name)
        
        power_state = 'unknown'
        for status in instance_view.statuses:
            if status.code.startswith('PowerState/'):
                power_state = status.code.split('/')[-1]
                break
        
        return {
            'status': 'found',
            'state': power_state,
            'vm_size': vm.hardware_profile.vm_size,
            'location': vm.location,
            'provisioning_state': vm.provisioning_state,
            'priority': vm.priority.value if vm.priority else 'Regular'
        }
        
    except Exception as e:
        logger.error(f"Failed to check Azure VM {vm_name}: {e}")
        return {'status': 'error', 'error': str(e)}


def check_s3_files(s3_bucket: str, s3_prefix: str) -> Dict[str, Any]:
    """Check S3 input files."""
    try:
        s3 = boto3.client('s3')
        
        response = s3.list_objects_v2(
            Bucket=s3_bucket,
            Prefix=s3_prefix
        )
        
        files = []
        total_size = 0
        
        for obj in response.get('Contents', []):
            files.append({
                'key': obj['Key'],
                'size': obj['Size'],
                'last_modified': obj['LastModified'].isoformat()
            })
            total_size += obj['Size']
        
        return {
            'status': 'found',
            'file_count': len(files),
            'total_size_bytes': total_size,
            'files': files[:10]  # Show first 10 files
        }
        
    except Exception as e:
        logger.error(f"Failed to check S3 files: {e}")
        return {'status': 'error', 'error': str(e)}


def check_gdrive_sync_status(gdrive_path: str) -> Dict[str, Any]:
    """Check Google Drive sync status (requires rclone)."""
    try:
        import subprocess
        
        # Use rclone to check if path exists and get file count
        result = subprocess.run(
            ['rclone', 'lsf', f'gdrive:{gdrive_path}', '--files-only'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            return {
                'status': 'accessible',
                'file_count': len(files),
                'files': files[:10]  # Show first 10 files
            }
        else:
            return {
                'status': 'not_accessible',
                'error': result.stderr
            }
            
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'error': 'rclone command timed out'}
    except FileNotFoundError:
        return {'status': 'rclone_not_found', 'error': 'rclone not installed'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def display_job_status(job: Dict[str, Any], detailed: bool = False):
    """Display formatted job status."""
    print("=" * 80)
    print(f"JOB STATUS: {job['job_id']}")
    print("=" * 80)
    
    # Basic job info
    print(f"Status: {job['status'].upper()}")
    print(f"Provider: {job['provider']}")
    print(f"Instance: {job['instance_type']} in {job['region']}")
    print(f"Created: {job['created_at']}")
    print(f"Updated: {job['updated_at']}")
    
    if job.get('started_at'):
        print(f"Started: {job['started_at']}")
    
    if job.get('completed_at'):
        print(f"Completed: {job['completed_at']}")
    
    # Cost information
    jm = get_job_manager()
    current_cost = jm.calculate_job_cost(job['job_id'])
    if current_cost > 0:
        print(f"Estimated cost: ${current_cost:.4f}")
    
    print()
    
    # Instance status
    if job.get('instance_id') and job['status'] in ['launched', 'running']:
        print("INSTANCE STATUS:")
        print("-" * 40)
        
        if job['provider'] == 'AWS':
            instance_status = check_aws_instance_status(job['instance_id'], job['region'])
        elif job['provider'] == 'GCP':
            # Need to parse zone from metadata
            metadata = job.get('metadata', {})
            zone = metadata.get('launch_result', {}).get('zone', f"{job['region']}-a")
            project_id = metadata.get('job_config', {}).get('project_id', '')
            instance_status = check_gcp_instance_status(job['instance_id'], project_id, zone)
        elif job['provider'] == 'Azure':
            metadata = job.get('metadata', {})
            resource_group = metadata.get('job_config', {}).get('resource_group', '')
            subscription_id = metadata.get('job_config', {}).get('subscription_id', '')
            instance_status = check_azure_instance_status(job['instance_id'], resource_group, subscription_id)
        else:
            instance_status = {'status': 'unsupported_provider'}
        
        if instance_status['status'] == 'found':
            print(f"State: {instance_status['state']}")
            if instance_status.get('public_ip'):
                print(f"Public IP: {instance_status['public_ip']}")
            if instance_status.get('private_ip'):
                print(f"Private IP: {instance_status['private_ip']}")
        elif instance_status['status'] == 'not_found':
            print("Instance not found (may have been terminated)")
        else:
            print(f"Unable to check instance: {instance_status.get('error', 'Unknown error')}")
        
        print()
    
    # S3 status
    if job.get('s3_input_path'):
        print("INPUT FILES (S3):")
        print("-" * 40)
        
        s3_bucket = job.get('s3_bucket', '')
        s3_prefix = job['s3_input_path'].replace(f's3://{s3_bucket}/', '')
        s3_status = check_s3_files(s3_bucket, s3_prefix)
        
        if s3_status['status'] == 'found':
            print(f"Files: {s3_status['file_count']}")
            print(f"Total size: {s3_status['total_size_bytes']:,} bytes")
            if detailed and s3_status['files']:
                print("Recent files:")
                for file_info in s3_status['files']:
                    print(f"  {file_info['key'].split('/')[-1]} ({file_info['size']:,} bytes)")
        else:
            print(f"Unable to check S3 files: {s3_status.get('error', 'Unknown error')}")
        
        print()
    
    # Google Drive status
    if job.get('gdrive_path'):
        print("RESULTS (Google Drive):")
        print("-" * 40)
        
        gdrive_status = check_gdrive_sync_status(job['gdrive_path'])
        
        if gdrive_status['status'] == 'accessible':
            print(f"Synced files: {gdrive_status['file_count']}")
            if detailed and gdrive_status['files']:
                print("Files:")
                for filename in gdrive_status['files']:
                    print(f"  {filename}")
        elif gdrive_status['status'] == 'not_accessible':
            print("No results synced yet (or path not accessible)")
        elif gdrive_status['status'] == 'rclone_not_found':
            print("Cannot check Google Drive (rclone not installed)")
        else:
            print(f"Unable to check Google Drive: {gdrive_status.get('error', 'Unknown error')}")
        
        print()
    
    # Additional details
    if detailed and job.get('metadata'):
        print("CONFIGURATION:")
        print("-" * 40)
        metadata = job['metadata']
        job_config = metadata.get('job_config', {})
        
        if job_config.get('basis_set'):
            print(f"Basis set: {job_config['basis_set']}")
        if job_config.get('shci_executable'):
            print(f"SHCI executable: {job_config['shci_executable']}")
        
        print()


def main():
    """Main function for cloud_status.py"""
    parser = argparse.ArgumentParser(description="Check status of a cloud job")
    parser.add_argument("job_id", help="Job ID to check")
    parser.add_argument("--detailed", "-d", action="store_true", 
                       help="Show detailed information")
    parser.add_argument("--json", action="store_true",
                       help="Output raw JSON instead of formatted display")
    
    args = parser.parse_args()
    
    # Get job from database
    jm = get_job_manager()
    job = jm.get_job(args.job_id)
    
    if not job:
        print(f"Job {args.job_id} not found")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(job, indent=2))
    else:
        display_job_status(job, args.detailed)


if __name__ == "__main__":
    main()