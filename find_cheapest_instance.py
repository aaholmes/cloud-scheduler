#!/usr/bin/env python3
"""
Find the cheapest spot instance across AWS, GCP, and Azure that meets hardware requirements.
"""
import boto3
import requests
import json
import logging
import argparse
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import billing_v1
from google.oauth2 import service_account
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default configuration (can be overridden)
DEFAULT_MIN_VCPU = 16
DEFAULT_MAX_VCPU = 32
DEFAULT_MIN_RAM_GB = 64
DEFAULT_MAX_RAM_GB = 256

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


def load_hardware_config(config_file: str) -> Dict[str, int]:
    """Load hardware requirements from config file."""
    config = {
        'min_vcpu': DEFAULT_MIN_VCPU,
        'max_vcpu': DEFAULT_MAX_VCPU,
        'min_ram_gb': DEFAULT_MIN_RAM_GB,
        'max_ram_gb': DEFAULT_MAX_RAM_GB
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
            
            # Check for hardware requirements in config
            if 'hardware' in file_config:
                hw_config = file_config['hardware']
                config.update({
                    'min_vcpu': hw_config.get('min_vcpu', config['min_vcpu']),
                    'max_vcpu': hw_config.get('max_vcpu', config['max_vcpu']),
                    'min_ram_gb': hw_config.get('min_ram_gb', config['min_ram_gb']),
                    'max_ram_gb': hw_config.get('max_ram_gb', config['max_ram_gb'])
                })
        except Exception as e:
            logger.warning(f"Could not load config file {config_file}: {e}")
    
    return config


def interactive_selection(sorted_instances: List[Dict[str, Any]], max_ram_gb: int) -> int:
    """Interactive selection menu for choosing instances."""
    if not sorted_instances:
        return -1
    
    # Calculate price per core for all instances
    for inst in sorted_instances:
        inst['price_per_core'] = inst['price_hr'] / inst['vcpu']
    
    # Sort by price per core
    by_price_per_core = sorted(sorted_instances, key=lambda x: x['price_per_core'])
    
    # Find options
    cheapest_per_core = by_price_per_core[0]
    cheapest_overall = sorted_instances[0]  # Already sorted by total price
    
    # Check if cheapest per-core and cheapest overall are the same
    same_instance = (cheapest_per_core['provider'] == cheapest_overall['provider'] and
                    cheapest_per_core['instance'] == cheapest_overall['instance'] and
                    cheapest_per_core['region'] == cheapest_overall['region'])
    
    # Find higher memory option with good per-core price
    higher_memory_option = None
    for inst in by_price_per_core[1:]:
        if inst['ram_gb'] > cheapest_per_core['ram_gb']:
            # Check if it's reasonably priced (within 20% per-core price)
            if inst['price_per_core'] <= cheapest_per_core['price_per_core'] * 1.2:
                higher_memory_option = inst
                break
    
    # If no higher memory option found, or if cheapest already has max memory
    if not higher_memory_option or cheapest_per_core['ram_gb'] >= max_ram_gb:
        higher_memory_option = None
    
    # Display options
    print("\n" + "="*100)
    print("INSTANCE SELECTION")
    print("="*100)
    
    print("\nOption 1 - Cheapest per-core instance:")
    print(f"  Provider: {cheapest_per_core['provider']}")
    print(f"  Instance: {cheapest_per_core['instance']}")
    print(f"  Region: {cheapest_per_core['region']}")
    print(f"  vCPUs: {cheapest_per_core['vcpu']}")
    print(f"  RAM: {cheapest_per_core['ram_gb']} GB")
    print(f"  Price: ${cheapest_per_core['price_hr']:.4f}/hour (${cheapest_per_core['price_per_core']:.4f}/core/hour)")
    
    option_num = 2
    if not same_instance:
        print(f"\nOption {option_num} - Cheapest overall instance:")
        print(f"  Provider: {cheapest_overall['provider']}")
        print(f"  Instance: {cheapest_overall['instance']}")
        print(f"  Region: {cheapest_overall['region']}")
        print(f"  vCPUs: {cheapest_overall['vcpu']}")
        print(f"  RAM: {cheapest_overall['ram_gb']} GB")
        print(f"  Price: ${cheapest_overall['price_hr']:.4f}/hour (${cheapest_overall['price_per_core']:.4f}/core/hour)")
        option_num += 1
    
    if higher_memory_option:
        print(f"\nOption {option_num} - Higher memory alternative:")
        print(f"  Provider: {higher_memory_option['provider']}")
        print(f"  Instance: {higher_memory_option['instance']}")
        print(f"  Region: {higher_memory_option['region']}")
        print(f"  vCPUs: {higher_memory_option['vcpu']}")
        print(f"  RAM: {higher_memory_option['ram_gb']} GB (+{higher_memory_option['ram_gb'] - cheapest_per_core['ram_gb']} GB)")
        print(f"  Price: ${higher_memory_option['price_hr']:.4f}/hour (${higher_memory_option['price_per_core']:.4f}/core/hour)")
        print(f"  Additional cost: +${higher_memory_option['price_hr'] - cheapest_per_core['price_hr']:.4f}/hour")
        
        memory_increase_pct = ((higher_memory_option['ram_gb'] - cheapest_per_core['ram_gb']) / cheapest_per_core['ram_gb']) * 100
        price_increase_pct = ((higher_memory_option['price_hr'] - cheapest_per_core['price_hr']) / cheapest_per_core['price_hr']) * 100
        print(f"  ({memory_increase_pct:.0f}% more memory for {price_increase_pct:.0f}% more cost)")
        memory_option_num = option_num
        option_num += 1
    else:
        memory_option_num = None
    
    print(f"\nOption {option_num} - Abort")
    abort_option = option_num
    
    # Get user choice
    valid_choices = ['1']
    if not same_instance:
        valid_choices.append('2')
    if higher_memory_option:
        valid_choices.append(str(memory_option_num))
    valid_choices.append(str(abort_option))
    
    while True:
        try:
            choice = input(f"\nSelect option ({', '.join(valid_choices)}): ").strip()
            if choice in valid_choices:
                choice = int(choice)
                break
            print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\nAborted by user.")
            return -1
    
    if choice == abort_option:
        print("Aborted by user.")
        return -1
    
    # Determine selected instance
    if choice == 1:
        selected = cheapest_per_core
    elif choice == 2 and not same_instance:
        selected = cheapest_overall
    elif choice == memory_option_num and higher_memory_option:
        selected = higher_memory_option
    else:
        selected = cheapest_per_core  # Fallback
    
    # Find the selected instance in the original sorted list
    for i, inst in enumerate(sorted_instances):
        if (inst['provider'] == selected['provider'] and 
            inst['instance'] == selected['instance'] and 
            inst['region'] == selected['region']):
            return i
    
    return 0  # Fallback to first instance


def main():
    """Main function to find cheapest spot instances."""
    parser = argparse.ArgumentParser(description="Find cheapest spot instances across cloud providers")
    parser.add_argument("--no-interactive", action="store_true", 
                       help="Skip interactive selection menu")
    parser.add_argument("--config", default="config.json",
                       help="Configuration file (default: config.json)")
    
    # Hardware requirement arguments
    parser.add_argument("--min-vcpu", type=int,
                       help=f"Minimum vCPUs (default: {DEFAULT_MIN_VCPU})")
    parser.add_argument("--max-vcpu", type=int,
                       help=f"Maximum vCPUs (default: {DEFAULT_MAX_VCPU})")
    parser.add_argument("--min-ram", type=int,
                       help=f"Minimum RAM in GB (default: {DEFAULT_MIN_RAM_GB})")
    parser.add_argument("--max-ram", type=int,
                       help=f"Maximum RAM in GB (default: {DEFAULT_MAX_RAM_GB})")
    
    args = parser.parse_args()
    
    # Load hardware configuration
    hw_config = load_hardware_config(args.config)
    
    # Override with command line arguments if provided
    min_vcpu = args.min_vcpu if args.min_vcpu is not None else hw_config['min_vcpu']
    max_vcpu = args.max_vcpu if args.max_vcpu is not None else hw_config['max_vcpu']
    min_ram_gb = args.min_ram if args.min_ram is not None else hw_config['min_ram_gb']
    max_ram_gb = args.max_ram if args.max_ram is not None else hw_config['max_ram_gb']
    
    # Validate ranges
    if min_vcpu > max_vcpu:
        logger.error("Minimum vCPUs cannot be greater than maximum vCPUs")
        sys.exit(1)
    
    if min_ram_gb > max_ram_gb:
        logger.error("Minimum RAM cannot be greater than maximum RAM")
        sys.exit(1)
    
    logger.info(f"Hardware requirements: {min_vcpu}-{max_vcpu} vCPUs, {min_ram_gb}-{max_ram_gb}GB RAM")
    
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
        if min_vcpu <= inst['vcpu'] <= max_vcpu and min_ram_gb <= inst['ram_gb'] <= max_ram_gb
    ]
    
    logger.info(f"Found {len(filtered)} instances meeting hardware requirements")
    
    # Sort by price
    sorted_instances = sorted(filtered, key=lambda x: x['price_hr'])
    
    # Display results
    print("\n" + "="*100)
    print(f"{'Provider':<8} | {'Instance Type':<20} | {'Region':<15} | {'vCPUs':<6} | {'RAM (GB)':<8} | {'$/hour':<10} | {'$/core/hr':<10}")
    print("="*100)
    
    for i, inst in enumerate(sorted_instances[:20]):  # Show top 20
        price_per_core = inst['price_hr'] / inst['vcpu']
        print(
            f"{inst['provider']:<8} | {inst['instance']:<20} | {inst['region']:<15} | "
            f"{inst['vcpu']:<6} | {inst['ram_gb']:<8} | ${inst['price_hr']:<9.4f} | ${price_per_core:<9.4f}"
        )
    
    if sorted_instances:
        if args.no_interactive:
            # Non-interactive mode - just save results
            print("\n" + "="*100)
            print(f"Cheapest option: {sorted_instances[0]['provider']} {sorted_instances[0]['instance']} "
                  f"in {sorted_instances[0]['region']} at ${sorted_instances[0]['price_hr']:.4f}/hour")
            
            with open('spot_prices.json', 'w') as f:
                json.dump(sorted_instances[:20], f, indent=2)
            print("\nTop 20 results saved to spot_prices.json")
        else:
            # Interactive selection
            selected_index = interactive_selection(sorted_instances, max_ram_gb)
            
            if selected_index >= 0:
                selected = sorted_instances[selected_index]
                print("\n" + "="*100)
                print(f"Selected: {selected['provider']} {selected['instance']} "
                      f"in {selected['region']} at ${selected['price_hr']:.4f}/hour")
                
                # Move selected instance to the top of the list
                sorted_instances.pop(selected_index)
                sorted_instances.insert(0, selected)
                
                # Save results to JSON with selected instance first
                with open('spot_prices.json', 'w') as f:
                    json.dump(sorted_instances[:20], f, indent=2)
                print("\nSelected instance saved as index 0 in spot_prices.json")
                print("Top 20 results saved to spot_prices.json")


if __name__ == "__main__":
    main()