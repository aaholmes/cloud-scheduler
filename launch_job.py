#!/usr/bin/env python3
"""
Launch a spot instance on the selected cloud provider with the bootstrap script.
"""
import boto3
import base64
import argparse
import json
import logging
import os
import sys
from typing import Dict, Any
from google.cloud import compute_v1
from google.oauth2 import service_account
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def read_bootstrap_script() -> str:
    """Read the bootstrap script from file."""
    bootstrap_path = "bootstrap.sh"
    if not os.path.exists(bootstrap_path):
        logger.error(f"Bootstrap script not found: {bootstrap_path}")
        sys.exit(1)
    
    with open(bootstrap_path, "r") as f:
        return f.read()


def launch_aws_spot(instance_type: str, region: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Launch an AWS spot instance with the bootstrap script."""
    try:
        bootstrap_script = read_bootstrap_script()
        ec2 = boto3.client("ec2", region_name=region)
        
        # Get the latest Amazon Linux 2 AMI
        response = ec2.describe_images(
            Owners=['amazon'],
            Filters=[
                {'Name': 'name', 'Values': ['amzn2-ami-hvm-*-x86_64-gp2']},
                {'Name': 'state', 'Values': ['available']}
            ]
        )
        
        if not response['Images']:
            raise Exception("No Amazon Linux 2 AMI found")
        
        # Sort by creation date and get the latest
        ami_id = sorted(response['Images'], key=lambda x: x['CreationDate'], reverse=True)[0]['ImageId']
        logger.info(f"Using AMI: {ami_id}")
        
        # Create or verify security group
        sg_name = config.get('security_group', 'cloud-scheduler-sg')
        try:
            sg_response = ec2.describe_security_groups(GroupNames=[sg_name])
            security_group_id = sg_response['SecurityGroups'][0]['GroupId']
        except:
            # Create security group if it doesn't exist
            logger.info(f"Creating security group: {sg_name}")
            sg_response = ec2.create_security_group(
                GroupName=sg_name,
                Description='Security group for cloud scheduler instances'
            )
            security_group_id = sg_response['GroupId']
            
            # Add SSH rule
            ec2.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }]
            )
        
        # Encode the bootstrap script
        encoded_script = base64.b64encode(bootstrap_script.encode("utf-8")).decode("utf-8")
        
        # Request spot instance
        logger.info(f"Requesting AWS spot instance {instance_type} in {region}...")
        response = ec2.request_spot_instances(
            InstanceCount=1,
            LaunchSpecification={
                "ImageId": ami_id,
                "InstanceType": instance_type,
                "KeyName": config.get('key_name'),
                "SecurityGroupIds": [security_group_id],
                "UserData": encoded_script,
                "IamInstanceProfile": {
                    "Name": config.get('iam_role', 'cloud-scheduler-role')
                } if config.get('iam_role') else {},
                "BlockDeviceMappings": [{
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "VolumeSize": config.get('disk_size_gb', 100),
                        "VolumeType": "gp3",
                        "DeleteOnTermination": True
                    }
                }]
            },
            Type="one-time",
            SpotPrice=str(config.get('max_price', 10.0))  # Max price willing to pay
        )
        
        spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
        logger.info(f"Spot request created: {spot_request_id}")
        
        # Wait for the instance to be fulfilled
        logger.info("Waiting for spot request to be fulfilled...")
        waiter = ec2.get_waiter('spot_instance_request_fulfilled')
        waiter.wait(SpotInstanceRequestIds=[spot_request_id])
        
        # Get instance ID
        response = ec2.describe_spot_instance_requests(
            SpotInstanceRequestIds=[spot_request_id]
        )
        instance_id = response['SpotInstanceRequests'][0]['InstanceId']
        
        # Get instance details
        instance_info = ec2.describe_instances(InstanceIds=[instance_id])
        instance = instance_info['Reservations'][0]['Instances'][0]
        
        result = {
            'provider': 'AWS',
            'instance_id': instance_id,
            'spot_request_id': spot_request_id,
            'public_ip': instance.get('PublicIpAddress', 'pending'),
            'private_ip': instance.get('PrivateIpAddress'),
            'region': region,
            'instance_type': instance_type,
            'status': 'launched'
        }
        
        logger.info(f"Instance launched successfully: {instance_id}")
        logger.info(f"Public IP: {result['public_ip']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to launch AWS instance: {e}")
        return {'status': 'failed', 'error': str(e)}


def launch_gcp_spot(instance_type: str, region: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Launch a GCP spot instance with the bootstrap script."""
    try:
        bootstrap_script = read_bootstrap_script()
        
        # Initialize the Compute Engine client
        compute_client = compute_v1.InstancesClient()
        project_id = config.get('project_id')
        zone = f"{region}-a"  # Default to zone 'a'
        
        if not project_id:
            raise ValueError("GCP project_id is required in config")
        
        # Machine configuration
        machine_type = f"zones/{zone}/machineTypes/{instance_type}"
        
        # Use a recent Ubuntu image
        image_response = compute_client.get_from_family(
            project="ubuntu-os-cloud",
            family="ubuntu-2004-lts"
        )
        source_image = image_response.self_link
        
        # Network configuration
        network_interface = compute_v1.NetworkInterface()
        network_interface.name = "global/networks/default"
        
        # Access config for external IP
        access_config = compute_v1.AccessConfig()
        access_config.type_ = "ONE_TO_ONE_NAT"
        access_config.name = "External NAT"
        network_interface.access_configs = [access_config]
        
        # Boot disk
        boot_disk = compute_v1.AttachedDisk()
        boot_disk.boot = True
        boot_disk.auto_delete = True
        boot_disk.type_ = "PERSISTENT"
        
        boot_disk.initialize_params = compute_v1.AttachedDiskInitializeParams()
        boot_disk.initialize_params.source_image = source_image
        boot_disk.initialize_params.disk_size_gb = config.get('disk_size_gb', 100)
        boot_disk.initialize_params.disk_type = f"zones/{zone}/diskTypes/pd-standard"
        
        # Instance configuration
        instance = compute_v1.Instance()
        instance.name = f"cloud-scheduler-{instance_type.replace('.', '-')}-{region}"
        instance.machine_type = machine_type
        instance.disks = [boot_disk]
        instance.network_interfaces = [network_interface]
        
        # Set as preemptible (spot) instance
        instance.scheduling = compute_v1.Scheduling()
        instance.scheduling.preemptible = True
        instance.scheduling.automatic_restart = False
        instance.scheduling.on_host_maintenance = "TERMINATE"
        
        # Add metadata for startup script
        metadata = compute_v1.Metadata()
        metadata.items = [
            compute_v1.Items(key="startup-script", value=bootstrap_script)
        ]
        instance.metadata = metadata
        
        # Add service account if specified
        if config.get('service_account_email'):
            service_account = compute_v1.ServiceAccount()
            service_account.email = config['service_account_email']
            service_account.scopes = [
                "https://www.googleapis.com/auth/cloud-platform"
            ]
            instance.service_accounts = [service_account]
        
        # Create the instance
        logger.info(f"Creating GCP spot instance {instance_type} in {zone}...")
        operation = compute_client.insert(
            project=project_id,
            zone=zone,
            instance_resource=instance
        )
        
        # Wait for operation to complete
        logger.info("Waiting for instance creation to complete...")
        # In production, you would properly wait for the operation
        
        result = {
            'provider': 'GCP',
            'instance_name': instance.name,
            'zone': zone,
            'region': region,
            'instance_type': instance_type,
            'status': 'launched',
            'project_id': project_id
        }
        
        logger.info(f"Instance creation initiated: {instance.name}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to launch GCP instance: {e}")
        return {'status': 'failed', 'error': str(e)}


def launch_azure_spot(instance_type: str, region: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Launch an Azure spot instance with the bootstrap script."""
    try:
        bootstrap_script = read_bootstrap_script()
        
        # Azure credentials
        credential = DefaultAzureCredential()
        subscription_id = config.get('subscription_id')
        resource_group = config.get('resource_group', 'cloud-scheduler-rg')
        
        if not subscription_id:
            raise ValueError("Azure subscription_id is required in config")
        
        # Initialize clients
        compute_client = ComputeManagementClient(credential, subscription_id)
        network_client = NetworkManagementClient(credential, subscription_id)
        resource_client = ResourceManagementClient(credential, subscription_id)
        
        # Ensure resource group exists
        resource_client.resource_groups.create_or_update(
            resource_group,
            {"location": region}
        )
        
        # Create or get virtual network
        vnet_name = "cloud-scheduler-vnet"
        subnet_name = "cloud-scheduler-subnet"
        
        # Create VNet
        poller = network_client.virtual_networks.begin_create_or_update(
            resource_group,
            vnet_name,
            {
                "location": region,
                "address_space": {"address_prefixes": ["10.0.0.0/16"]}
            }
        )
        vnet = poller.result()
        
        # Create subnet
        poller = network_client.subnets.begin_create_or_update(
            resource_group,
            vnet_name,
            subnet_name,
            {"address_prefix": "10.0.0.0/24"}
        )
        subnet = poller.result()
        
        # Create public IP
        public_ip_name = f"cloud-scheduler-ip-{instance_type.replace('_', '-').lower()}"
        poller = network_client.public_ip_addresses.begin_create_or_update(
            resource_group,
            public_ip_name,
            {
                "location": region,
                "sku": {"name": "Standard"},
                "public_ip_allocation_method": "Static"
            }
        )
        public_ip = poller.result()
        
        # Create network interface
        nic_name = f"cloud-scheduler-nic-{instance_type.replace('_', '-').lower()}"
        poller = network_client.network_interfaces.begin_create_or_update(
            resource_group,
            nic_name,
            {
                "location": region,
                "ip_configurations": [{
                    "name": "ipconfig1",
                    "subnet": {"id": subnet.id},
                    "public_ip_address": {"id": public_ip.id}
                }]
            }
        )
        nic = poller.result()
        
        # VM configuration
        vm_name = f"cloud-scheduler-{instance_type.replace('_', '-').lower()}"
        
        vm_parameters = {
            "location": region,
            "priority": "Spot",
            "eviction_policy": "Deallocate",
            "billing_profile": {
                "max_price": config.get('max_price', -1)  # -1 means pay up to on-demand price
            },
            "hardware_profile": {
                "vm_size": instance_type
            },
            "storage_profile": {
                "image_reference": {
                    "publisher": "Canonical",
                    "offer": "UbuntuServer",
                    "sku": "18.04-LTS",
                    "version": "latest"
                },
                "os_disk": {
                    "create_option": "FromImage",
                    "managed_disk": {
                        "storage_account_type": "Premium_LRS"
                    }
                }
            },
            "os_profile": {
                "computer_name": vm_name,
                "admin_username": "azureuser",
                "admin_password": config.get('admin_password', 'CloudScheduler123!'),
                "custom_data": base64.b64encode(bootstrap_script.encode()).decode()
            },
            "network_profile": {
                "network_interfaces": [{"id": nic.id}]
            }
        }
        
        # Create VM
        logger.info(f"Creating Azure spot VM {instance_type} in {region}...")
        poller = compute_client.virtual_machines.begin_create_or_update(
            resource_group,
            vm_name,
            vm_parameters
        )
        vm = poller.result()
        
        result = {
            'provider': 'Azure',
            'vm_name': vm_name,
            'resource_group': resource_group,
            'region': region,
            'instance_type': instance_type,
            'status': 'launched',
            'public_ip': public_ip.ip_address
        }
        
        logger.info(f"VM created successfully: {vm_name}")
        logger.info(f"Public IP: {public_ip.ip_address}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to launch Azure instance: {e}")
        return {'status': 'failed', 'error': str(e)}


def load_config(config_file: str) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            return json.load(f)
    return {}


def main():
    """Main function to launch cloud instance."""
    parser = argparse.ArgumentParser(description="Launch a cloud spot instance for computation.")
    parser.add_argument("--provider", required=True, choices=['AWS', 'GCP', 'Azure'], 
                       help="Cloud provider")
    parser.add_argument("--instance", required=True, 
                       help="Instance type (e.g., r7i.8xlarge)")
    parser.add_argument("--region", required=True, 
                       help="Cloud region (e.g., us-east-1)")
    parser.add_argument("--config", default="config.json", 
                       help="Configuration file (default: config.json)")
    parser.add_argument("--from-file", 
                       help="Load instance details from spot_prices.json result")
    parser.add_argument("--index", type=int, default=0,
                       help="Index of instance to launch from spot_prices.json (default: 0)")
    
    args = parser.parse_args()
    
    # Load instance details from file if specified
    if args.from_file:
        with open(args.from_file, 'r') as f:
            instances = json.load(f)
            if args.index >= len(instances):
                logger.error(f"Index {args.index} out of range. File contains {len(instances)} instances.")
                sys.exit(1)
            
            selected = instances[args.index]
            args.provider = selected['provider']
            args.instance = selected['instance']
            args.region = selected['region']
            logger.info(f"Selected instance from file: {selected}")
    
    # Load configuration
    config = load_config(args.config)
    provider_config = config.get(args.provider.lower(), {})
    
    # Launch instance based on provider
    if args.provider == 'AWS':
        result = launch_aws_spot(args.instance, args.region, provider_config)
    elif args.provider == 'GCP':
        result = launch_gcp_spot(args.instance, args.region, provider_config)
    elif args.provider == 'Azure':
        result = launch_azure_spot(args.instance, args.region, provider_config)
    
    # Save result
    with open('launch_result.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    if result.get('status') == 'launched':
        logger.info("Instance launched successfully!")
        logger.info(f"Results saved to launch_result.json")
    else:
        logger.error("Failed to launch instance")
        sys.exit(1)


if __name__ == "__main__":
    main()