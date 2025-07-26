#!/usr/bin/env python3
"""
Cost Tracker - Integrates with cloud provider billing APIs to retrieve actual costs.
Supports AWS Cost Explorer, GCP Cloud Billing, and Azure Cost Management APIs.
"""
import boto3
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from job_manager import get_job_manager

try:
    from google.cloud import billing_v1
    from google.cloud import asset_v1
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logging.warning("Google Cloud libraries not available. GCP cost tracking disabled.")

try:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.resource import ResourceManagementClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logging.warning("Azure libraries not available. Azure cost tracking disabled.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CloudCostTracker:
    """Retrieves actual costs from cloud provider billing APIs."""
    
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.job_manager = get_job_manager()
        
        # Initialize cloud clients
        self.aws_cost_client = None
        self.aws_ec2_client = None
        self.gcp_billing_client = None
        self.azure_cost_client = None
        
        self._init_aws_clients()
        self._init_gcp_clients()
        self._init_azure_clients()
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration file."""
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found. Using defaults.")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            return {}
    
    def _init_aws_clients(self):
        """Initialize AWS clients."""
        try:
            aws_config = self.config.get('aws', {})
            region = aws_config.get('region', 'us-east-1')
            
            # Cost Explorer is only available in us-east-1
            self.aws_cost_client = boto3.client('ce', region_name='us-east-1')
            self.aws_ec2_client = boto3.client('ec2', region_name=region)
            
            logger.info("AWS clients initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize AWS clients: {e}")
    
    def _init_gcp_clients(self):
        """Initialize GCP clients."""
        if not GOOGLE_AVAILABLE:
            return
        
        try:
            self.gcp_billing_client = billing_v1.CloudBillingClient()
            logger.info("GCP clients initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize GCP clients: {e}")
    
    def _init_azure_clients(self):
        """Initialize Azure clients."""
        if not AZURE_AVAILABLE:
            return
        
        try:
            azure_config = self.config.get('azure', {})
            subscription_id = azure_config.get('subscription_id')
            
            if subscription_id:
                credential = DefaultAzureCredential()
                self.azure_cost_client = CostManagementClient(credential)
                logger.info("Azure clients initialized successfully")
            else:
                logger.warning("Azure subscription_id not found in config")
        except Exception as e:
            logger.warning(f"Failed to initialize Azure clients: {e}")
    
    def get_aws_spot_cost(self, job_id: str, instance_id: str, region: str, 
                         start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
        """Retrieve AWS spot instance cost using Cost Explorer API."""
        if not self.aws_cost_client:
            logger.error("AWS Cost Explorer client not available")
            return None
        
        try:
            # Format dates for Cost Explorer API
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            logger.info(f"Querying AWS costs for instance {instance_id} from {start_str} to {end_str}")
            
            # Query costs with resource-level granularity
            response = self.aws_cost_client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_str,
                    'End': end_str
                },
                Granularity='DAILY',
                Metrics=['BlendedCost', 'UsageQuantity'],
                GroupBy=[
                    {'Type': 'DIMENSION', 'Key': 'RESOURCE_ID'},
                    {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
                ],
                Filter={
                    'And': [
                        {
                            'Dimensions': {
                                'Key': 'RESOURCE_ID',
                                'Values': [instance_id]
                            }
                        },
                        {
                            'Dimensions': {
                                'Key': 'USAGE_TYPE',
                                'Values': ['*SpotUsage*'],
                                'MatchOptions': ['CONTAINS']
                            }
                        }
                    ]
                }
            )
            
            total_cost = 0.0
            cost_breakdown = []
            
            for result in response.get('ResultsByTime', []):
                for group in result.get('Groups', []):
                    cost_amount = float(group['Metrics']['BlendedCost']['Amount'])
                    usage_amount = float(group['Metrics']['UsageQuantity']['Amount'])
                    
                    if cost_amount > 0:
                        total_cost += cost_amount
                        
                        cost_breakdown.append({
                            'provider': 'AWS',
                            'cost_type': 'spot_compute',
                            'amount': cost_amount,
                            'currency': group['Metrics']['BlendedCost']['Unit'],
                            'usage_quantity': usage_amount,
                            'usage_unit': group['Metrics']['UsageQuantity']['Unit'],
                            'billing_period_start': result['TimePeriod']['Start'],
                            'billing_period_end': result['TimePeriod']['End'],
                            'raw_data': group
                        })
            
            if total_cost > 0:
                logger.info(f"Retrieved AWS cost for job {job_id}: ${total_cost:.4f}")
                return {
                    'total_cost': total_cost,
                    'breakdown': cost_breakdown,
                    'currency': 'USD',
                    'provider': 'AWS'
                }
            else:
                logger.warning(f"No cost data found for AWS instance {instance_id}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve AWS costs for job {job_id}: {e}")
            return None
    
    def get_gcp_spot_cost(self, job_id: str, instance_name: str, project_id: str, zone: str,
                         start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
        """Retrieve GCP preemptible instance cost."""
        if not self.gcp_billing_client:
            logger.error("GCP billing client not available")
            return None
        
        # Note: GCP requires BigQuery export for detailed cost analysis
        # This is a placeholder implementation that would need BigQuery integration
        logger.warning("GCP cost retrieval requires BigQuery billing export setup")
        logger.info("Consider implementing BigQuery-based cost analysis for GCP")
        
        # For now, return estimated cost based on pricing API
        try:
            # This would require implementing GCP pricing API integration
            # and calculating costs based on instance runtime
            estimated_cost = self._estimate_gcp_cost(instance_name, project_id, zone, start_date, end_date)
            
            if estimated_cost:
                return {
                    'total_cost': estimated_cost,
                    'breakdown': [{
                        'provider': 'GCP',
                        'cost_type': 'preemptible_compute_estimated',
                        'amount': estimated_cost,
                        'currency': 'USD',
                        'billing_period_start': start_date.isoformat(),
                        'billing_period_end': end_date.isoformat(),
                        'raw_data': {'note': 'Estimated cost - requires BigQuery export for actual costs'}
                    }],
                    'currency': 'USD',
                    'provider': 'GCP',
                    'estimated': True
                }
        except Exception as e:
            logger.error(f"Failed to estimate GCP costs for job {job_id}: {e}")
        
        return None
    
    def get_azure_spot_cost(self, job_id: str, vm_name: str, resource_group: str,
                           start_date: datetime, end_date: datetime) -> Optional[Dict[str, Any]]:
        """Retrieve Azure spot VM cost using Cost Management API."""
        if not self.azure_cost_client:
            logger.error("Azure cost client not available")
            return None
        
        try:
            azure_config = self.config.get('azure', {})
            subscription_id = azure_config.get('subscription_id')
            
            if not subscription_id:
                logger.error("Azure subscription_id not configured")
                return None
            
            # Format scope for subscription-level query
            scope = f"/subscriptions/{subscription_id}"
            
            # Prepare query definition
            query_definition = {
                "type": "Usage",
                "timeframe": "Custom",
                "timePeriod": {
                    "from": start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    "to": end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                },
                "dataset": {
                    "granularity": "Daily",
                    "aggregation": {
                        "totalCost": {
                            "name": "Cost",
                            "function": "Sum"
                        }
                    },
                    "grouping": [
                        {
                            "type": "Dimension",
                            "name": "ResourceId"
                        }
                    ],
                    "filter": {
                        "dimensions": {
                            "name": "ResourceId",
                            "operator": "Contains",
                            "values": [vm_name]
                        }
                    }
                }
            }
            
            logger.info(f"Querying Azure costs for VM {vm_name} in resource group {resource_group}")
            
            # Execute query
            response = self.azure_cost_client.query.usage(scope, query_definition)
            
            total_cost = 0.0
            cost_breakdown = []
            
            for row in response.rows:
                cost_amount = float(row[0])  # Cost column
                resource_id = row[1]  # ResourceId column
                
                if cost_amount > 0:
                    total_cost += cost_amount
                    
                    cost_breakdown.append({
                        'provider': 'Azure',
                        'cost_type': 'spot_compute',
                        'amount': cost_amount,
                        'currency': 'USD',  # Azure Cost Management typically returns USD
                        'resource_id': resource_id,
                        'billing_period_start': start_date.isoformat(),
                        'billing_period_end': end_date.isoformat(),
                        'raw_data': {'row': row}
                    })
            
            if total_cost > 0:
                logger.info(f"Retrieved Azure cost for job {job_id}: ${total_cost:.4f}")
                return {
                    'total_cost': total_cost,
                    'breakdown': cost_breakdown,
                    'currency': 'USD',
                    'provider': 'Azure'
                }
            else:
                logger.warning(f"No cost data found for Azure VM {vm_name}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve Azure costs for job {job_id}: {e}")
            return None
    
    def _estimate_gcp_cost(self, instance_name: str, project_id: str, zone: str,
                          start_date: datetime, end_date: datetime) -> Optional[float]:
        """Estimate GCP cost based on pricing API (placeholder implementation)."""
        # This would require implementing GCP pricing API integration
        # For now, return None to indicate actual implementation needed
        return None
    
    def retrieve_job_cost(self, job_id: str, force_refresh: bool = False) -> bool:
        """Retrieve actual cost for a completed job."""
        job = self.job_manager.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return False
        
        # Skip if cost already retrieved and not forcing refresh
        if job.get('actual_cost') is not None and not force_refresh:
            logger.info(f"Cost already retrieved for job {job_id}")
            return True
        
        # Only retrieve costs for completed jobs
        if job['status'] not in ['completed', 'failed', 'terminated']:
            logger.warning(f"Job {job_id} is not completed (status: {job['status']})")
            return False
        
        # Determine date range for cost query
        start_date = datetime.fromisoformat(job.get('started_at') or job['created_at'])
        end_date = datetime.fromisoformat(job.get('completed_at') or datetime.now().isoformat())
        
        # Add buffer to account for billing delays
        start_date = start_date - timedelta(hours=1)
        end_date = end_date + timedelta(hours=1)
        
        cost_data = None
        provider = job['provider'].upper()
        
        try:
            if provider == 'AWS':
                cost_data = self.get_aws_spot_cost(
                    job_id, job['instance_id'], job['region'], start_date, end_date
                )
            elif provider == 'GCP':
                metadata = json.loads(job.get('metadata', '{}'))
                launch_result = metadata.get('launch_result', {})
                cost_data = self.get_gcp_spot_cost(
                    job_id, launch_result.get('instance_name', ''), 
                    launch_result.get('project_id', ''), launch_result.get('zone', ''),
                    start_date, end_date
                )
            elif provider == 'AZURE':
                metadata = json.loads(job.get('metadata', '{}'))
                launch_result = metadata.get('launch_result', {})
                cost_data = self.get_azure_spot_cost(
                    job_id, launch_result.get('vm_name', ''), 
                    launch_result.get('resource_group', ''),
                    start_date, end_date
                )
            else:
                logger.error(f"Unsupported provider: {provider}")
                return False
            
            if cost_data:
                # Update job record with actual cost
                success = self.job_manager.update_actual_cost(
                    job_id, cost_data['total_cost'], cost_data['breakdown']
                )
                
                if success:
                    logger.info(f"Successfully updated cost for job {job_id}: ${cost_data['total_cost']:.4f}")
                    return True
                else:
                    logger.error(f"Failed to update cost in database for job {job_id}")
                    return False
            else:
                logger.warning(f"No cost data retrieved for job {job_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error retrieving cost for job {job_id}: {e}")
            return False
    
    def batch_retrieve_costs(self, max_jobs: int = 10, days_back: int = 7) -> Dict[str, Any]:
        """Retrieve costs for multiple completed jobs."""
        # Get completed jobs without cost data
        jobs = self.job_manager.list_jobs(limit=max_jobs * 2)  # Get more to filter
        
        cutoff_date = datetime.now() - timedelta(days=days_back)
        eligible_jobs = []
        
        for job in jobs:
            # Only process jobs that are completed and don't have cost data
            if (job['status'] in ['completed', 'failed', 'terminated'] and 
                job.get('actual_cost') is None and
                datetime.fromisoformat(job['created_at']) >= cutoff_date):
                eligible_jobs.append(job)
        
        # Limit to max_jobs
        eligible_jobs = eligible_jobs[:max_jobs]
        
        results = {
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'jobs': []
        }
        
        for job in eligible_jobs:
            job_id = job['job_id']
            logger.info(f"Processing cost retrieval for job {job_id}")
            
            success = self.retrieve_job_cost(job_id)
            results['processed'] += 1
            
            if success:
                results['successful'] += 1
                results['jobs'].append({'job_id': job_id, 'status': 'success'})
            else:
                results['failed'] += 1
                results['jobs'].append({'job_id': job_id, 'status': 'failed'})
            
            # Add delay to respect rate limits
            time.sleep(1)
        
        logger.info(f"Batch cost retrieval completed: {results['successful']}/{results['processed']} successful")
        return results


def main():
    """Main function for standalone cost retrieval."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Retrieve actual costs for cloud jobs")
    parser.add_argument("--job-id", help="Specific job ID to process")
    parser.add_argument("--batch", action="store_true", help="Process multiple jobs")
    parser.add_argument("--max-jobs", type=int, default=10, help="Maximum jobs to process in batch")
    parser.add_argument("--days-back", type=int, default=7, help="How many days back to look for jobs")
    parser.add_argument("--force-refresh", action="store_true", help="Force refresh existing cost data")
    parser.add_argument("--config", default="config.json", help="Configuration file")
    
    args = parser.parse_args()
    
    tracker = CloudCostTracker(args.config)
    
    if args.job_id:
        # Process single job
        success = tracker.retrieve_job_cost(args.job_id, args.force_refresh)
        if success:
            logger.info(f"Successfully retrieved cost for job {args.job_id}")
        else:
            logger.error(f"Failed to retrieve cost for job {args.job_id}")
            exit(1)
    
    elif args.batch:
        # Process multiple jobs
        results = tracker.batch_retrieve_costs(args.max_jobs, args.days_back)
        logger.info(f"Batch processing results: {results}")
    
    else:
        logger.error("Please specify --job-id or --batch")
        exit(1)


if __name__ == "__main__":
    main()