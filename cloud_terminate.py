#!/usr/bin/env python3
"""
Terminate a running cloud job instance.
"""
import argparse
import json
import sys
import boto3
import logging
from typing import Dict, Any
from job_manager import get_job_manager
from google.cloud import compute_v1
from azure.mgmt.compute import ComputeManagementClient
from azure.identity import DefaultAzureCredential

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def terminate_aws_instance(instance_id: str, region: str) -> Dict[str, Any]:
    """Terminate AWS instance."""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        
        # First check if instance exists
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            if not response['Reservations']:
                return {'status': 'not_found', 'message': 'Instance not found'}
            
            instance = response['Reservations'][0]['Instances'][0]
            current_state = instance['State']['Name']
            
            if current_state in ['terminated', 'terminating']:
                return {'status': 'already_terminated', 'message': f'Instance is already {current_state}'}
        
        except Exception as e:
            return {'status': 'error', 'message': f'Could not check instance status: {str(e)}'}
        
        # Terminate the instance
        response = ec2.terminate_instances(InstanceIds=[instance_id])
        
        if response['TerminatingInstances']:
            terminating_instance = response['TerminatingInstances'][0]
            return {
                'status': 'success',
                'message': 'Instance termination initiated',
                'previous_state': terminating_instance['PreviousState']['Name'],
                'current_state': terminating_instance['CurrentState']['Name']
            }
        else:
            return {'status': 'error', 'message': 'Failed to terminate instance'}
    
    except Exception as e:
        logger.error(f"Failed to terminate AWS instance {instance_id}: {e}")
        return {'status': 'error', 'message': str(e)}


def terminate_gcp_instance(instance_name: str, project_id: str, zone: str) -> Dict[str, Any]:
    """Terminate GCP instance."""
    try:
        compute_client = compute_v1.InstancesClient()
        
        # Check if instance exists
        try:
            instance = compute_client.get(
                project=project_id,
                zone=zone,
                instance=instance_name
            )
            
            if instance.status.lower() in ['terminated', 'stopping']:
                return {'status': 'already_terminated', 'message': f'Instance is already {instance.status.lower()}'}
        
        except Exception as e:
            return {'status': 'not_found', 'message': 'Instance not found'}
        
        # Delete the instance
        operation = compute_client.delete(
            project=project_id,
            zone=zone,
            instance=instance_name
        )
        
        return {
            'status': 'success',
            'message': 'Instance deletion initiated',
            'operation_id': operation.name
        }
    
    except Exception as e:
        logger.error(f"Failed to terminate GCP instance {instance_name}: {e}")
        return {'status': 'error', 'message': str(e)}


def terminate_azure_instance(vm_name: str, resource_group: str, subscription_id: str) -> Dict[str, Any]:
    """Terminate Azure VM."""
    try:
        credential = DefaultAzureCredential()
        compute_client = ComputeManagementClient(credential, subscription_id)
        
        # Check if VM exists
        try:
            vm = compute_client.virtual_machines.get(resource_group, vm_name)
            
            # Get power state
            instance_view = compute_client.virtual_machines.instance_view(resource_group, vm_name)
            for status in instance_view.statuses:
                if status.code.startswith('PowerState/'):
                    current_state = status.code.split('/')[-1]
                    if current_state in ['deallocated', 'stopped']:
                        return {'status': 'already_terminated', 'message': f'VM is already {current_state}'}
                    break
        
        except Exception as e:
            return {'status': 'not_found', 'message': 'VM not found'}
        
        # Delete (deallocate and delete) the VM
        poller = compute_client.virtual_machines.begin_delete(resource_group, vm_name)
        
        return {
            'status': 'success',
            'message': 'VM deletion initiated',
            'operation_id': poller.result().name if hasattr(poller.result(), 'name') else 'unknown'
        }
    
    except Exception as e:
        logger.error(f"Failed to terminate Azure VM {vm_name}: {e}")
        return {'status': 'error', 'message': str(e)}


def cleanup_spot_instance_request(instance_id: str, region: str) -> Dict[str, Any]:
    """Cancel AWS spot instance request if it exists."""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        
        # Find spot instance request associated with this instance
        response = ec2.describe_spot_instance_requests(
            Filters=[
                {'Name': 'instance-id', 'Values': [instance_id]}
            ]
        )
        
        if response['SpotInstanceRequests']:
            spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
            
            # Cancel the spot request
            ec2.cancel_spot_instance_requests(SpotInstanceRequestIds=[spot_request_id])
            
            return {
                'status': 'success',
                'message': f'Cancelled spot instance request {spot_request_id}'
            }
        else:
            return {'status': 'no_spot_request', 'message': 'No associated spot instance request found'}
    
    except Exception as e:
        return {'status': 'error', 'message': f'Error handling spot request: {str(e)}'}


def final_resync_before_termination(job: Dict[str, Any]) -> bool:
    """Attempt a final sync before terminating."""
    try:
        from cloud_resync import trigger_resync_via_ssh
        
        print("Attempting final sync before termination...")
        
        # Construct sync command
        gdrive_path = job.get('gdrive_path', 'shci_jobs/unknown')
        sync_command = f'cd $HOME && ./sync_results.sh shci_output gdrive "{gdrive_path}"'
        
        result = trigger_resync_via_ssh(job, sync_command)
        
        if result['status'] == 'success':
            print("✓ Final sync completed")
            return True
        else:
            print(f"⚠ Final sync failed: {result['message']}")
            return False
    
    except Exception as e:
        print(f"⚠ Could not perform final sync: {str(e)}")
        return False


def main():
    """Main function for cloud_terminate.py"""
    parser = argparse.ArgumentParser(description="Terminate a cloud job instance")
    parser.add_argument("job_id", help="Job ID to terminate")
    parser.add_argument("--force", action="store_true",
                       help="Force termination without confirmation")
    parser.add_argument("--no-final-sync", action="store_true",
                       help="Skip final sync attempt before termination")
    parser.add_argument("--reason", default="Manual termination",
                       help="Reason for termination (for logging)")
    
    args = parser.parse_args()
    
    # Get job from database
    jm = get_job_manager()
    job = jm.get_job(args.job_id)
    
    if not job:
        print(f"Job {args.job_id} not found")
        sys.exit(1)
    
    print(f"Job {args.job_id}: {job['status']}")
    print(f"Provider: {job['provider']}")
    print(f"Instance: {job.get('instance_type', 'Unknown')} in {job['region']}")
    print(f"Instance ID: {job.get('instance_id', 'Not available')}")
    
    # Calculate current cost
    current_cost = jm.calculate_job_cost(args.job_id)
    if current_cost > 0:
        print(f"Estimated cost so far: ${current_cost:.4f}")
    
    print()
    
    # Check if job is already terminated
    if job['status'] in ['completed', 'failed', 'terminated']:
        print(f"Job is already in {job['status']} state.")
        if not args.force:
            print("Use --force to attempt termination anyway.")
            sys.exit(0)
    
    # Check if we have instance information
    if not job.get('instance_id'):
        print("No instance ID available - cannot terminate")
        sys.exit(1)
    
    # Confirmation prompt
    if not args.force:
        response = input("Are you sure you want to terminate this job? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            print("Termination cancelled")
            sys.exit(0)
    
    # Attempt final sync unless disabled
    if not args.no_final_sync and job.get('public_ip') and job['status'] in ['launched', 'running']:
        final_resync_before_termination(job)
    
    # Terminate based on provider
    print(f"Terminating {job['provider']} instance...")
    
    if job['provider'] == 'AWS':
        result = terminate_aws_instance(job['instance_id'], job['region'])
        
        # Also cleanup spot instance request if applicable
        if result['status'] == 'success':
            spot_cleanup = cleanup_spot_instance_request(job['instance_id'], job['region'])
            if spot_cleanup['status'] == 'success':
                print(f"Also cancelled spot instance request")
    
    elif job['provider'] == 'GCP':
        metadata = job.get('metadata', {})
        project_id = metadata.get('job_config', {}).get('project_id', '')
        zone = metadata.get('launch_result', {}).get('zone', f"{job['region']}-a")
        
        if not project_id:
            print("Error: No GCP project ID found in job metadata")
            sys.exit(1)
        
        result = terminate_gcp_instance(job['instance_id'], project_id, zone)
    
    elif job['provider'] == 'Azure':
        metadata = job.get('metadata', {})
        resource_group = metadata.get('job_config', {}).get('resource_group', '')
        subscription_id = metadata.get('job_config', {}).get('subscription_id', '')
        
        if not resource_group or not subscription_id:
            print("Error: No Azure resource group or subscription ID found in job metadata")
            sys.exit(1)
        
        result = terminate_azure_instance(job['instance_id'], resource_group, subscription_id)
    
    else:
        print(f"Unsupported provider: {job['provider']}")
        sys.exit(1)
    
    # Handle result
    if result['status'] == 'success':
        print(f"✓ {result['message']}")
        
        # Update job status in database
        jm.update_job_status(args.job_id, 'terminated', {
            'termination_reason': args.reason,
            'final_cost': current_cost
        })
        
        print(f"Job {args.job_id} marked as terminated in database")
        
    elif result['status'] == 'already_terminated':
        print(f"ℹ {result['message']}")
        
        # Update database if not already marked as terminated
        if job['status'] != 'terminated':
            jm.update_job_status(args.job_id, 'terminated')
    
    elif result['status'] == 'not_found':
        print(f"⚠ {result['message']}")
        print("Instance may have already been terminated or cleaned up")
        
        # Update database
        jm.update_job_status(args.job_id, 'terminated', {
            'termination_reason': 'Instance not found'
        })
    
    else:
        print(f"✗ Termination failed: {result['message']}")
        sys.exit(1)


if __name__ == "__main__":
    main()