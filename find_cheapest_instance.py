#!/usr/bin/env python3
"""
Find the cheapest spot instance across AWS, GCP, and Azure that meets hardware requirements.
"""
import boto3
import requests
import json
import logging
import argparse
import re
import sys
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def get_aws_instance_types(min_vcpu: int = 1, max_vcpu: int = 128, 
                          min_ram_gb: int = 1, max_ram_gb: int = 1024) -> Dict[str, tuple]:
    """Query AWS EC2 API for available instance types matching requirements."""
    try:
        ec2 = boto3.client('ec2', region_name='us-east-1')
        
        paginator = ec2.get_paginator('describe_instance_types')
        instance_types = {}
        
        for page in paginator.paginate():
            for instance_type in page['InstanceTypes']:
                name = instance_type['InstanceType']
                vcpu = instance_type['VCpuInfo']['DefaultVCpus']
                memory_mb = instance_type['MemoryInfo']['SizeInMiB']
                memory_gb = memory_mb // 1024
                
                # Filter based on requirements
                if (min_vcpu <= vcpu <= max_vcpu and 
                    min_ram_gb <= memory_gb <= max_ram_gb):
                    instance_types[name] = (vcpu, memory_gb)
        
        logger.info(f"Found {len(instance_types)} AWS instance types matching requirements")
        return instance_types
        
    except Exception as e:
        logger.warning(f"Failed to query AWS instance types dynamically: {e}")
        # Fallback to a basic set if API fails
        return {
            'r5.4xlarge': (16, 128), 'r5.8xlarge': (32, 256),
            'm5.4xlarge': (16, 64), 'm5.8xlarge': (32, 128)
        }

def get_gcp_instance_types(min_vcpu: int = 1, max_vcpu: int = 128,
                          min_ram_gb: int = 1, max_ram_gb: int = 1024) -> Dict[str, tuple]:
    """Query GCP Compute Engine API for available machine types matching requirements."""
    try:
        from googleapiclient import discovery
        from google.oauth2 import service_account
        import google.auth
        
        # Try to get credentials
        try:
            credentials, project = google.auth.default()
        except Exception:
            # If no credentials available, use fallback
            raise Exception("No GCP credentials available")
            
        compute = discovery.build('compute', 'v1', credentials=credentials)
        
        # Get machine types from a representative zone (us-central1-a)
        request = compute.machineTypes().list(project=project, zone='us-central1-a')
        response = request.execute()
        
        instance_types = {}
        for machine_type in response.get('items', []):
            name = machine_type['name']
            vcpu = machine_type['guestCpus']
            memory_mb = machine_type['memoryMb']
            memory_gb = memory_mb // 1024
            
            # Filter based on requirements  
            if (min_vcpu <= vcpu <= max_vcpu and 
                min_ram_gb <= memory_gb <= max_ram_gb):
                instance_types[name] = (vcpu, memory_gb)
        
        logger.info(f"Found {len(instance_types)} GCP machine types matching requirements")
        return instance_types
        
    except Exception as e:
        logger.warning(f"Failed to query GCP machine types dynamically: {e}")
        # Fallback to a basic set if API fails
        return {
            'n2-highmem-16': (16, 128), 'n2-highmem-32': (32, 256),
            'n2-standard-16': (16, 64), 'n2-standard-32': (32, 128)
        }

def get_azure_instance_types(min_vcpu: int = 1, max_vcpu: int = 128,
                            min_ram_gb: int = 1, max_ram_gb: int = 1024) -> Dict[str, tuple]:
    """Query Azure Compute SKUs API for available VM sizes matching requirements."""
    try:
        # Use Azure REST API directly since it's simpler than installing Azure SDK
        api_url = "https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Compute/skus"
        
        # For now, we'll use the retail prices API which has VM size info
        # This is a simplified approach - in production you'd use proper Azure SDK
        retail_api = "https://prices.azure.com/api/retail/prices"
        query = "$filter=serviceName eq 'Virtual Machines' and priceType eq 'Consumption'"
        
        response = requests.get(f"{retail_api}?{query}")
        if response.status_code != 200:
            raise Exception(f"Failed to query Azure API: {response.status_code}")
        
        data = response.json()
        instance_types = {}
        
        for item in data.get('Items', []):
            if 'armSkuName' in item and item.get('type') == 'Consumption':
                sku_name = item['armSkuName']
                
                # Parse vCPUs and memory from the SKU attributes or product name
                # This is a heuristic approach since the API doesn't always provide structured specs
                if '_' in sku_name:
                    parts = sku_name.split('_')
                    if len(parts) >= 2:
                        size_part = parts[1]  # e.g., "E16s" from "Standard_E16s_v5"
                        
                        # Extract number from size (e.g., "16" from "E16s")
                        vcpu_match = re.search(r'(\d+)', size_part)
                        if vcpu_match:
                            vcpu = int(vcpu_match.group(1))
                            
                            # Estimate memory based on Azure VM series patterns
                            if size_part.startswith('E'):  # Memory optimized
                                memory_gb = vcpu * 8  # E-series typically has 8GB per vCPU
                            elif size_part.startswith('D'):  # General purpose
                                memory_gb = vcpu * 4  # D-series typically has 4GB per vCPU
                            elif size_part.startswith('F'):  # Compute optimized
                                memory_gb = vcpu * 2  # F-series typically has 2GB per vCPU
                            else:
                                memory_gb = vcpu * 4  # Default assumption
                            
                            # Filter based on requirements
                            if (min_vcpu <= vcpu <= max_vcpu and 
                                min_ram_gb <= memory_gb <= max_ram_gb):
                                instance_types[sku_name] = (vcpu, memory_gb)
        
        logger.info(f"Found {len(instance_types)} Azure VM sizes matching requirements")
        return instance_types
        
    except Exception as e:
        logger.warning(f"Failed to query Azure VM sizes dynamically: {e}")
        # Fallback to a basic set if API fails
        return {
            'Standard_E16s_v5': (16, 128), 'Standard_E32s_v5': (32, 256),
            'Standard_D16s_v5': (16, 64), 'Standard_D32s_v5': (32, 128)
        }


def get_aws_spot_prices(hw_config: Dict[str, int]) -> List[Dict[str, Any]]:
    """Query AWS for spot prices of instances matching hardware requirements."""
    logger.info("Querying AWS spot prices...")
    instances = []
    
    # Get dynamic instance types based on hardware requirements
    aws_instance_specs = get_aws_instance_types(
        hw_config['min_vcpu'], hw_config['max_vcpu'],
        hw_config['min_ram_gb'], hw_config['max_ram_gb']
    )
    
    if not aws_instance_specs:
        logger.warning("No AWS instance types found matching requirements")
        return instances
    
    try:
        # Get list of regions
        ec2 = boto3.client('ec2', region_name='us-east-1')
        regions_response = ec2.describe_regions()
        regions = [r['RegionName'] for r in regions_response['Regions']]
        
        # Query each region in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_region = {}
            
            for region in regions:
                future = executor.submit(query_aws_region_spot_prices, region, aws_instance_specs)
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


def query_aws_region_spot_prices(region: str, aws_instance_specs: Dict[str, tuple]) -> List[Dict[str, Any]]:
    """Query spot prices for a specific AWS region."""
    instances = []
    
    try:
        client = boto3.client('ec2', region_name=region)
        
        # Get spot prices for our instance types
        instance_types = list(aws_instance_specs.keys())
        
        # AWS API has limits, so we need to batch requests if we have many instance types
        batch_size = 100  # AWS allows up to 100 instance types per request
        for i in range(0, len(instance_types), batch_size):
            batch_types = instance_types[i:i + batch_size]
            
            response = client.describe_spot_price_history(
                InstanceTypes=batch_types,
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
                
                if instance_type in aws_instance_specs:
                    vcpu, ram_gb = aws_instance_specs[instance_type]
                    
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


def get_gcp_spot_prices(hw_config: Dict[str, int]) -> List[Dict[str, Any]]:
    """Query GCP for spot prices of instances matching hardware requirements."""
    logger.info("Querying GCP spot prices...")
    instances = []
    
    # Get dynamic instance types based on hardware requirements
    gcp_instance_specs = get_gcp_instance_types(
        hw_config['min_vcpu'], hw_config['max_vcpu'],
        hw_config['min_ram_gb'], hw_config['max_ram_gb']
    )
    
    if not gcp_instance_specs:
        logger.warning("No GCP machine types found matching requirements")
        return instances
    
    try:
        # GCP regions
        regions = [
            'us-central1', 'us-east1', 'us-east4', 'us-west1', 'us-west2',
            'europe-west1', 'europe-west2', 'europe-west3', 'europe-west4',
            'asia-east1', 'asia-northeast1', 'asia-southeast1'
        ]
        
        # Generate estimated pricing for dynamic instance types
        # In production, you would use the Cloud Billing Catalog API
        # For now, we'll estimate based on vCPU and memory
        spot_discount = 0.35  # Spot instances are typically 60-70% off
        
        for region in regions:
            for instance_type, (vcpu, ram_gb) in gcp_instance_specs.items():
                # Estimate base price based on vCPU and memory
                # GCP pricing is roughly $0.048/hour per vCore + $0.0065/hour per GB RAM
                base_vcpu_price = vcpu * 0.048
                base_memory_price = ram_gb * 0.0065
                base_price = base_vcpu_price + base_memory_price
                
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


def get_azure_spot_prices(hw_config: Dict[str, int]) -> List[Dict[str, Any]]:
    """Query Azure for spot prices of instances matching hardware requirements."""
    logger.info("Querying Azure spot prices...")
    instances = []
    
    # Get dynamic instance types based on hardware requirements
    azure_instance_specs = get_azure_instance_types(
        hw_config['min_vcpu'], hw_config['max_vcpu'],
        hw_config['min_ram_gb'], hw_config['max_ram_gb']
    )
    
    if not azure_instance_specs:
        logger.warning("No Azure VM sizes found matching requirements")
        return instances
    
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
            for instance_name, (vcpu, ram_gb) in azure_instance_specs.items():
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
    
    # Budget filtering
    parser.add_argument("--max-price-per-hour", type=float,
                       help="Maximum price per hour in USD")
    parser.add_argument("--budget", type=float,
                       help="Total budget limit in USD")
    parser.add_argument("--estimated-runtime", type=float, default=2.0,
                       help="Estimated runtime in hours for budget calculation (default: 2.0)")
    
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
            executor.submit(get_aws_spot_prices, hw_config): 'AWS',
            executor.submit(get_gcp_spot_prices, hw_config): 'GCP',
            executor.submit(get_azure_spot_prices, hw_config): 'Azure'
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
    
    # Apply budget filtering if specified
    if args.max_price_per_hour is not None:
        before_count = len(filtered)
        filtered = [inst for inst in filtered if inst['price_hr'] <= args.max_price_per_hour]
        logger.info(f"Budget filter (max ${args.max_price_per_hour:.4f}/hour): {before_count} -> {len(filtered)} instances")
    
    if args.budget is not None:
        max_hourly_cost = args.budget / args.estimated_runtime
        before_count = len(filtered)
        filtered = [inst for inst in filtered if inst['price_hr'] <= max_hourly_cost]
        logger.info(f"Budget filter (${args.budget:.2f} budget / {args.estimated_runtime}h = max ${max_hourly_cost:.4f}/hour): {before_count} -> {len(filtered)} instances")
    
    if not filtered:
        logger.error("No instances meet the specified requirements and budget constraints")
        logger.error("Try adjusting --min-vcpu, --max-vcpu, --min-ram, --max-ram, --budget, or --estimated-runtime")
        return
    
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