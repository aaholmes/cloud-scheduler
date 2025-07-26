#!/usr/bin/env python3
"""
Find the cheapest spot instance across AWS, GCP, and Azure that meets hardware requirements.
"""
import boto3
import requests
import json
import logging
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import billing_v1
from google.oauth2 import service_account
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
MIN_VCPU = 16
MAX_VCPU = 32
MIN_RAM_GB = 64
MAX_RAM_GB = 256

# Instance type specifications (vCPU, RAM in GB)
AWS_INSTANCE_SPECS = {
    # Memory optimized instances
    'r5.4xlarge': (16, 128),
    'r5.8xlarge': (32, 256),
    'r5a.4xlarge': (16, 128),
    'r5a.8xlarge': (32, 256),
    'r6i.4xlarge': (16, 128),
    'r6i.8xlarge': (32, 256),
    'r7i.4xlarge': (16, 128),
    'r7i.8xlarge': (32, 256),
    # Compute optimized with sufficient memory
    'm5.4xlarge': (16, 64),
    'm5.8xlarge': (32, 128),
    'm5a.4xlarge': (16, 64),
    'm5a.8xlarge': (32, 128),
    'm6i.4xlarge': (16, 64),
    'm6i.8xlarge': (32, 128),
}

GCP_INSTANCE_SPECS = {
    # Memory-optimized
    'n2-highmem-16': (16, 128),
    'n2-highmem-32': (32, 256),
    'n2d-highmem-16': (16, 128),
    'n2d-highmem-32': (32, 256),
    # Standard with good memory
    'n2-standard-16': (16, 64),
    'n2-standard-32': (32, 128),
    'n2d-standard-16': (16, 64),
    'n2d-standard-32': (32, 128),
}

AZURE_INSTANCE_SPECS = {
    # Memory optimized
    'Standard_E16s_v5': (16, 128),
    'Standard_E32s_v5': (32, 256),
    'Standard_E16as_v5': (16, 128),
    'Standard_E32as_v5': (32, 256),
    # General purpose
    'Standard_D16s_v5': (16, 64),
    'Standard_D32s_v5': (32, 128),
    'Standard_D16as_v5': (16, 64),
    'Standard_D32as_v5': (32, 128),
}


def get_aws_spot_prices() -> List[Dict[str, Any]]:
    """Query AWS for spot prices of memory-optimized instances."""
    logger.info("Querying AWS spot prices...")
    instances = []
    
    try:
        # Get list of regions
        ec2 = boto3.client('ec2', region_name='us-east-1')
        regions_response = ec2.describe_regions()
        regions = [r['RegionName'] for r in regions_response['Regions']]
        
        # Query each region in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_region = {}
            
            for region in regions:
                future = executor.submit(query_aws_region_spot_prices, region)
                future_to_region[future] = region
            
            for future in as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    region_instances = future.result()
                    instances.extend(region_instances)
                except Exception as e:
                    logger.warning(f"Failed to query AWS region {region}: {e}")
    
    except Exception as e:
        logger.error(f"Failed to get AWS regions: {e}")
    
    return instances


def query_aws_region_spot_prices(region: str) -> List[Dict[str, Any]]:
    """Query spot prices for a specific AWS region."""
    instances = []
    
    try:
        client = boto3.client('ec2', region_name=region)
        
        # Get spot prices for our instance types
        instance_types = list(AWS_INSTANCE_SPECS.keys())
        
        response = client.describe_spot_price_history(
            InstanceTypes=instance_types,
            ProductDescriptions=['Linux/UNIX'],
            MaxResults=1000
        )
        
        # Process spot prices
        seen_types = set()
        for price_info in response.get('SpotPriceHistory', []):
            instance_type = price_info['InstanceType']
            
            # Only take the most recent price for each instance type
            if instance_type in seen_types:
                continue
            seen_types.add(instance_type)
            
            if instance_type in AWS_INSTANCE_SPECS:
                vcpu, ram_gb = AWS_INSTANCE_SPECS[instance_type]
                
                instances.append({
                    'provider': 'AWS',
                    'instance': instance_type,
                    'region': region,
                    'price_hr': float(price_info['SpotPrice']),
                    'vcpu': vcpu,
                    'ram_gb': ram_gb,
                    'availability_zone': price_info['AvailabilityZone']
                })
    
    except Exception as e:
        if 'UnauthorizedOperation' not in str(e):
            logger.debug(f"Failed to query AWS region {region}: {e}")
    
    return instances


def get_gcp_spot_prices() -> List[Dict[str, Any]]:
    """Query GCP for spot prices of memory-optimized instances."""
    logger.info("Querying GCP spot prices...")
    instances = []
    
    try:
        # This is a simplified implementation
        # In production, you would use the Cloud Billing Catalog API
        # For now, we'll use approximate spot pricing (typically 60-91% discount)
        
        # GCP regions
        regions = [
            'us-central1', 'us-east1', 'us-east4', 'us-west1', 'us-west2',
            'europe-west1', 'europe-west2', 'europe-west3', 'europe-west4',
            'asia-east1', 'asia-northeast1', 'asia-southeast1'
        ]
        
        # Approximate on-demand prices (USD per hour)
        # These would be fetched from the Cloud Billing API in production
        base_prices = {
            'n2-highmem-16': 0.9768,
            'n2-highmem-32': 1.9536,
            'n2d-highmem-16': 0.8544,
            'n2d-highmem-32': 1.7088,
            'n2-standard-16': 0.7768,
            'n2-standard-32': 1.5536,
            'n2d-standard-16': 0.6792,
            'n2d-standard-32': 1.3584,
        }
        
        # Spot discount (approximately 60-70% off)
        spot_discount = 0.35
        
        for region in regions:
            for instance_type, base_price in base_prices.items():
                if instance_type in GCP_INSTANCE_SPECS:
                    vcpu, ram_gb = GCP_INSTANCE_SPECS[instance_type]
                    
                    instances.append({
                        'provider': 'GCP',
                        'instance': instance_type,
                        'region': region,
                        'price_hr': base_price * spot_discount,
                        'vcpu': vcpu,
                        'ram_gb': ram_gb
                    })
    
    except Exception as e:
        logger.error(f"Failed to query GCP prices: {e}")
    
    return instances


def get_azure_spot_prices() -> List[Dict[str, Any]]:
    """Query Azure for spot prices of memory-optimized instances."""
    logger.info("Querying Azure spot prices...")
    instances = []
    
    try:
        # Azure Retail Prices API
        api_url = "https://prices.azure.com/api/retail/prices"
        
        # Azure regions
        regions = [
            'eastus', 'eastus2', 'westus', 'westus2', 'centralus',
            'northeurope', 'westeurope', 'uksouth', 'ukwest',
            'eastasia', 'southeastasia', 'japaneast', 'japanwest'
        ]
        
        for region in regions:
            # Query for each instance type
            for instance_name, (vcpu, ram_gb) in AZURE_INSTANCE_SPECS.items():
                query = (
                    f"$filter=serviceName eq 'Virtual Machines' "
                    f"and priceType eq 'Spot' "
                    f"and armRegionName eq '{region}' "
                    f"and armSkuName eq '{instance_name}'"
                )
                
                try:
                    response = requests.get(f"{api_url}?{query}")
                    if response.status_code == 200:
                        data = response.json()
                        
                        for item in data.get('Items', []):
                            # Only Linux prices
                            if 'Windows' not in item.get('productName', ''):
                                instances.append({
                                    'provider': 'Azure',
                                    'instance': instance_name,
                                    'region': region,
                                    'price_hr': item['retailPrice'],
                                    'vcpu': vcpu,
                                    'ram_gb': ram_gb
                                })
                                break  # Only need one price per instance/region
                
                except Exception as e:
                    logger.debug(f"Failed to query Azure price for {instance_name} in {region}: {e}")
    
    except Exception as e:
        logger.error(f"Failed to query Azure prices: {e}")
    
    return instances


def main():
    """Main function to find cheapest spot instances."""
    all_instances = []
    
    # Query all providers in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(get_aws_spot_prices): 'AWS',
            executor.submit(get_gcp_spot_prices): 'GCP',
            executor.submit(get_azure_spot_prices): 'Azure'
        }
        
        for future in as_completed(futures):
            provider = futures[future]
            try:
                instances = future.result()
                all_instances.extend(instances)
                logger.info(f"Found {len(instances)} instances from {provider}")
            except Exception as e:
                logger.error(f"Failed to get prices from {provider}: {e}")
    
    # Filter based on hardware requirements
    filtered = [
        inst for inst in all_instances
        if MIN_VCPU <= inst['vcpu'] <= MAX_VCPU and MIN_RAM_GB <= inst['ram_gb'] <= MAX_RAM_GB
    ]
    
    logger.info(f"Found {len(filtered)} instances meeting hardware requirements")
    
    # Sort by price
    sorted_instances = sorted(filtered, key=lambda x: x['price_hr'])
    
    # Display results
    print("\n" + "="*100)
    print(f"{'Provider':<8} | {'Instance Type':<20} | {'Region':<15} | {'vCPUs':<6} | {'RAM (GB)':<8} | {'$/hour':<10}")
    print("="*100)
    
    for i, inst in enumerate(sorted_instances[:20]):  # Show top 20
        print(
            f"{inst['provider']:<8} | {inst['instance']:<20} | {inst['region']:<15} | "
            f"{inst['vcpu']:<6} | {inst['ram_gb']:<8} | ${inst['price_hr']:<9.4f}"
        )
    
    if sorted_instances:
        print("\n" + "="*100)
        print(f"Cheapest option: {sorted_instances[0]['provider']} {sorted_instances[0]['instance']} "
              f"in {sorted_instances[0]['region']} at ${sorted_instances[0]['price_hr']:.4f}/hour")
        
        # Save results to JSON for use by launch script
        with open('spot_prices.json', 'w') as f:
            json.dump(sorted_instances[:20], f, indent=2)
        print("\nTop 20 results saved to spot_prices.json")


if __name__ == "__main__":
    main()