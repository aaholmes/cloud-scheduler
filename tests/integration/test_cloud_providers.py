"""Integration tests for cloud provider APIs and authentication."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock
import boto3
from moto import mock_ec2
import sys

# Add project root to path for imports  
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from find_cheapest_instance import get_aws_spot_prices, get_gcp_prices, get_azure_prices
from launch_job import AWSLauncher, GCPLauncher, AzureLauncher


@mock_ec2
class TestAWSIntegration:
    """Test AWS API integration."""
    
    def setup_method(self):
        """Set up AWS mocks."""
        self.ec2_client = boto3.client('ec2', region_name='us-east-1')
        
        # Create mock VPC and security group
        vpc = self.ec2_client.create_vpc(CidrBlock='10.0.0.0/16')
        self.vpc_id = vpc['Vpc']['VpcId']
        
        sg = self.ec2_client.create_security_group(
            GroupName='test-sg',
            Description='Test security group',
            VpcId=self.vpc_id
        )
        self.sg_id = sg['GroupId']
    
    def test_aws_spot_price_retrieval(self):
        """Test AWS spot price API integration."""
        # Create mock spot price history
        with patch('boto3.client') as mock_boto:
            mock_ec2 = MagicMock()
            mock_boto.return_value = mock_ec2
            
            mock_ec2.describe_spot_price_history.return_value = {
                'SpotPrices': [
                    {
                        'InstanceType': 'r5.4xlarge',
                        'SpotPrice': '0.512',
                        'AvailabilityZone': 'us-east-1a',
                        'ProductDescription': 'Linux/UNIX'
                    },
                    {
                        'InstanceType': 'r5.8xlarge', 
                        'SpotPrice': '1.024',
                        'AvailabilityZone': 'us-east-1b',
                        'ProductDescription': 'Linux/UNIX'
                    }
                ]
            }
            
            # Mock instance type details
            with patch('find_cheapest_instance.get_instance_details') as mock_details:
                mock_details.side_effect = [
                    {'vcpu': 16, 'ram_gb': 128},
                    {'vcpu': 32, 'ram_gb': 256}
                ]
                
                prices = get_aws_spot_prices('us-east-1', min_vcpu=16, max_vcpu=64)
                
                assert len(prices) == 2
                assert prices[0]['provider'] == 'AWS'
                assert prices[0]['instance'] == 'r5.4xlarge'
                assert prices[0]['price_hr'] == 0.512
                assert prices[0]['vcpu'] == 16
                assert prices[0]['ram_gb'] == 128
    
    def test_aws_instance_launch_integration(self, sample_config):
        """Test AWS instance launch integration."""
        config = sample_config['aws']
        config['security_group'] = self.sg_id
        
        launcher = AWSLauncher(config)
        
        # Mock the launch process
        with patch.object(launcher, 'ec2_client') as mock_ec2:
            mock_ec2.run_instances.return_value = {
                'Instances': [{
                    'InstanceId': 'i-1234567890',
                    'State': {'Name': 'pending'},
                    'PublicIpAddress': '54.123.45.67',
                    'PrivateIpAddress': '10.0.1.100'
                }]
            }
            
            mock_ec2.describe_instances.return_value = {
                'Reservations': [{
                    'Instances': [{
                        'InstanceId': 'i-1234567890',
                        'State': {'Name': 'running'},
                        'PublicIpAddress': '54.123.45.67',
                        'PrivateIpAddress': '10.0.1.100'
                    }]
                }]
            }
            
            result = launcher.launch_instance(
                instance_type='r5.4xlarge',
                region='us-east-1',
                user_data='#!/bin/bash\necho "test"'
            )
            
            assert result['status'] == 'launched'
            assert result['instance_id'] == 'i-1234567890'
            assert result['public_ip'] == '54.123.45.67'
            assert result['private_ip'] == '10.0.1.100'
    
    def test_aws_authentication_error_handling(self):
        """Test AWS authentication error handling."""
        with patch('boto3.client') as mock_boto:
            mock_boto.side_effect = Exception("Invalid credentials")
            
            prices = get_aws_spot_prices('us-east-1')
            assert prices == []  # Should return empty list on auth error


class TestGCPIntegration:
    """Test GCP API integration."""
    
    @patch('googleapiclient.discovery.build')
    def test_gcp_pricing_integration(self, mock_build):
        """Test GCP pricing API integration."""
        mock_compute = MagicMock()
        mock_build.return_value = mock_compute
        
        # Mock machine types response
        mock_compute.machineTypes().list().execute.return_value = {
            'items': [
                {
                    'name': 'n2-highmem-16',
                    'guestCpus': 16,
                    'memoryMb': 131072,  # 128GB in MB
                    'zone': 'https://www.googleapis.com/compute/v1/projects/test/zones/us-central1-a'
                }
            ]
        }
        
        # Mock pricing (simplified - in reality would need billing API)
        with patch('find_cheapest_instance.get_gcp_pricing') as mock_pricing:
            mock_pricing.return_value = {'n2-highmem-16': 0.489}
            
            prices = get_gcp_prices('us-central1', project_id='test-project')
            
            assert len(prices) >= 1
            assert prices[0]['provider'] == 'GCP'
            assert prices[0]['instance'] == 'n2-highmem-16'
            assert prices[0]['vcpu'] == 16 
            assert prices[0]['ram_gb'] == 128
    
    @patch('googleapiclient.discovery.build')  
    def test_gcp_instance_launch_integration(self, mock_build, sample_config):
        """Test GCP instance launch integration."""
        mock_compute = MagicMock()
        mock_build.return_value = mock_compute
        
        config = sample_config['gcp']
        launcher = GCPLauncher(config)
        
        # Mock instance creation
        mock_compute.instances().insert().execute.return_value = {
            'name': 'operation-12345',
            'status': 'RUNNING'
        }
        
        mock_compute.instances().get().execute.return_value = {
            'name': 'test-instance',
            'status': 'RUNNING',
            'networkInterfaces': [{
                'accessConfigs': [{'natIP': '34.123.45.67'}],
                'networkIP': '10.0.1.100'
            }]
        }
        
        result = launcher.launch_instance(
            instance_type='n2-highmem-16',
            region='us-central1-a',
            startup_script='#!/bin/bash\necho "test"'
        )
        
        assert result['status'] == 'launched'
        assert result['public_ip'] == '34.123.45.67'
        assert result['private_ip'] == '10.0.1.100'
    
    @patch('googleapiclient.discovery.build')
    def test_gcp_authentication_error_handling(self, mock_build):
        """Test GCP authentication error handling."""
        mock_build.side_effect = Exception("Authentication failed")
        
        prices = get_gcp_prices('us-central1', project_id='test-project')
        assert prices == []


class TestAzureIntegration:
    """Test Azure API integration."""
    
    @patch('azure.mgmt.compute.ComputeManagementClient')
    def test_azure_pricing_integration(self, mock_compute_client):
        """Test Azure pricing API integration."""
        mock_client = MagicMock()
        mock_compute_client.return_value = mock_client
        
        # Mock VM sizes response
        mock_client.virtual_machine_sizes.list.return_value = [
            MagicMock(
                name='Standard_E16s_v5',
                number_of_cores=16,
                memory_in_mb=131072,  # 128GB
                max_data_disk_count=32
            )
        ]
        
        # Mock pricing
        with patch('find_cheapest_instance.get_azure_pricing') as mock_pricing:
            mock_pricing.return_value = {'Standard_E16s_v5': 0.534}
            
            prices = get_azure_prices('eastus', subscription_id='test-sub')
            
            assert len(prices) >= 1
            assert prices[0]['provider'] == 'Azure'
            assert prices[0]['instance'] == 'Standard_E16s_v5'
            assert prices[0]['vcpu'] == 16
            assert prices[0]['ram_gb'] == 128
    
    @patch('azure.mgmt.compute.ComputeManagementClient')
    @patch('azure.mgmt.network.NetworkManagementClient')
    def test_azure_instance_launch_integration(self, mock_network_client, mock_compute_client, sample_config):
        """Test Azure instance launch integration."""
        mock_compute = MagicMock()
        mock_network = MagicMock()
        mock_compute_client.return_value = mock_compute
        mock_network_client.return_value = mock_network
        
        config = sample_config['azure']
        launcher = AzureLauncher(config)
        
        # Mock VM creation
        mock_operation = MagicMock()
        mock_operation.result.return_value = MagicMock(
            name='test-vm',
            provisioning_state='Succeeded'
        )
        mock_compute.virtual_machines.begin_create_or_update.return_value = mock_operation
        
        # Mock network interface and public IP
        mock_network.public_ip_addresses.get.return_value = MagicMock(
            ip_address='20.123.45.67'
        )
        mock_network.network_interfaces.get.return_value = MagicMock(
            ip_configurations=[MagicMock(
                private_ip_address='10.0.1.100',
                public_ip_address=MagicMock(id='/subscriptions/test/publicIPs/test-ip')
            )]
        )
        
        result = launcher.launch_instance(
            instance_type='Standard_E16s_v5',
            region='eastus',
            custom_data='#!/bin/bash\necho "test"'
        )
        
        assert result['status'] == 'launched'
        assert result['public_ip'] == '20.123.45.67'
        assert result['private_ip'] == '10.0.1.100'


class TestMultiCloudPriceComparison:
    """Test multi-cloud price comparison integration."""
    
    @patch('find_cheapest_instance.get_aws_spot_prices')
    @patch('find_cheapest_instance.get_gcp_prices')
    @patch('find_cheapest_instance.get_azure_prices')
    def test_multi_cloud_price_aggregation(self, mock_azure, mock_gcp, mock_aws):
        """Test aggregation of prices from all cloud providers."""
        # Mock responses from each provider
        mock_aws.return_value = [{
            'provider': 'AWS',
            'instance': 'r5.4xlarge',
            'vcpu': 16,
            'ram_gb': 128,
            'price_hr': 0.512,
            'region': 'us-east-1'
        }]
        
        mock_gcp.return_value = [{
            'provider': 'GCP',
            'instance': 'n2-highmem-16',
            'vcpu': 16,
            'ram_gb': 128,
            'price_hr': 0.489,
            'region': 'us-central1'
        }]
        
        mock_azure.return_value = [{
            'provider': 'Azure',
            'instance': 'Standard_E16s_v5',
            'vcpu': 16,
            'ram_gb': 128,
            'price_hr': 0.534,
            'region': 'eastus'
        }]
        
        # Import and run the main price discovery function
        from find_cheapest_instance import main as find_main
        
        with patch('sys.argv', ['find_cheapest_instance.py', '--no-interactive']):
            with patch('builtins.print'):  # Suppress output
                find_main()
        
        # Verify spot_prices.json was created with all providers
        assert os.path.exists('spot_prices.json')
        
        with open('spot_prices.json', 'r') as f:
            prices = json.load(f)
        
        providers = {price['provider'] for price in prices}
        assert 'AWS' in providers
        assert 'GCP' in providers  
        assert 'Azure' in providers
        
        # Verify cheapest instance is selected (GCP in this case)
        cheapest = min(prices, key=lambda x: x['price_hr'])
        assert cheapest['provider'] == 'GCP'
        assert cheapest['price_hr'] == 0.489
        
        # Clean up
        if os.path.exists('spot_prices.json'):
            os.remove('spot_prices.json')
    
    def test_provider_failure_handling(self):
        """Test handling when some cloud providers fail."""
        with patch('find_cheapest_instance.get_aws_spot_prices', return_value=[]):
            with patch('find_cheapest_instance.get_gcp_prices', side_effect=Exception("GCP API error")):
                with patch('find_cheapest_instance.get_azure_prices', return_value=[{
                    'provider': 'Azure',
                    'instance': 'Standard_E16s_v5',
                    'price_hr': 0.534
                }]):
                    
                    from find_cheapest_instance import main as find_main
                    
                    with patch('sys.argv', ['find_cheapest_instance.py', '--no-interactive']):
                        with patch('builtins.print'):
                            # Should not crash even if some providers fail
                            find_main()
                    
                    # Should still create spot_prices.json with available data
                    if os.path.exists('spot_prices.json'):
                        with open('spot_prices.json', 'r') as f:
                            prices = json.load(f)
                        
                        # Should only have Azure results
                        providers = {price['provider'] for price in prices}
                        assert providers == {'Azure'}
                        
                        os.remove('spot_prices.json')


class TestCloudCredentialsValidation:
    """Test cloud credentials validation."""
    
    def test_aws_credentials_validation(self):
        """Test AWS credentials validation."""
        # Test with invalid credentials
        with patch.dict(os.environ, {'AWS_ACCESS_KEY_ID': 'invalid', 'AWS_SECRET_ACCESS_KEY': 'invalid'}):
            with patch('boto3.client') as mock_boto:
                mock_boto.side_effect = Exception("The security token included in the request is invalid")
                
                prices = get_aws_spot_prices('us-east-1')
                assert prices == []
    
    def test_gcp_credentials_validation(self):
        """Test GCP credentials validation."""
        with patch('googleapiclient.discovery.build') as mock_build:
            mock_build.side_effect = Exception("Invalid service account credentials")
            
            prices = get_gcp_prices('us-central1', project_id='invalid-project')
            assert prices == []
    
    def test_azure_credentials_validation(self):
        """Test Azure credentials validation."""
        with patch('azure.mgmt.compute.ComputeManagementClient') as mock_client:
            mock_client.side_effect = Exception("Authentication failed")
            
            prices = get_azure_prices('eastus', subscription_id='invalid-subscription')
            assert prices == []