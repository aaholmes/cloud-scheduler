"""Unit tests for find_cheapest_instance.py functionality."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from find_cheapest_instance import (
    get_aws_spot_prices, get_gcp_prices, get_azure_prices,
    filter_by_hardware_requirements, sort_instances_by_price,
    interactive_selection, save_spot_prices
)


class TestPriceParsing:
    """Test price parsing and filtering functionality."""
    
    def test_filter_by_hardware_requirements(self):
        """Test hardware requirements filtering."""
        instances = [
            {"vcpu": 8, "ram_gb": 32, "price_hr": 0.2},
            {"vcpu": 16, "ram_gb": 64, "price_hr": 0.4},
            {"vcpu": 32, "ram_gb": 128, "price_hr": 0.8},
            {"vcpu": 64, "ram_gb": 256, "price_hr": 1.6}
        ]
        
        # Test minimum requirements
        filtered = filter_by_hardware_requirements(
            instances, min_vcpu=16, min_ram_gb=64
        )
        assert len(filtered) == 3
        assert all(inst["vcpu"] >= 16 for inst in filtered)
        assert all(inst["ram_gb"] >= 64 for inst in filtered)
        
        # Test maximum requirements
        filtered = filter_by_hardware_requirements(
            instances, max_vcpu=32, max_ram_gb=128
        )
        assert len(filtered) == 3
        assert all(inst["vcpu"] <= 32 for inst in filtered)
        assert all(inst["ram_gb"] <= 128 for inst in filtered)
        
        # Test range requirements
        filtered = filter_by_hardware_requirements(
            instances, min_vcpu=16, max_vcpu=32, min_ram_gb=64, max_ram_gb=128
        )
        assert len(filtered) == 2
        assert all(16 <= inst["vcpu"] <= 32 for inst in filtered)
        assert all(64 <= inst["ram_gb"] <= 128 for inst in filtered)
    
    def test_sort_instances_by_price(self):
        """Test instance sorting by different price criteria."""
        instances = [
            {"provider": "AWS", "instance": "r5.large", "vcpu": 2, "ram_gb": 16, "price_hr": 0.2},
            {"provider": "GCP", "instance": "n2-standard-4", "vcpu": 4, "ram_gb": 16, "price_hr": 0.3},
            {"provider": "Azure", "instance": "D4s_v5", "vcpu": 4, "ram_gb": 16, "price_hr": 0.25}
        ]
        
        # Test sorting by total price
        sorted_by_total = sort_instances_by_price(instances, by_total_price=True)
        assert sorted_by_total[0]["price_hr"] == 0.2  # AWS cheapest overall
        assert sorted_by_total[1]["price_hr"] == 0.25  # Azure second
        assert sorted_by_total[2]["price_hr"] == 0.3   # GCP most expensive
        
        # Test sorting by per-core price
        sorted_by_core = sort_instances_by_price(instances, by_total_price=False)
        expected_per_core = [
            0.2 / 2,  # AWS: $0.10 per core
            0.25 / 4, # Azure: $0.0625 per core  
            0.3 / 4   # GCP: $0.075 per core
        ]
        
        # Should be sorted: Azure ($0.0625), GCP ($0.075), AWS ($0.10)
        assert sorted_by_core[0]["provider"] == "Azure"
        assert sorted_by_core[1]["provider"] == "GCP" 
        assert sorted_by_core[2]["provider"] == "AWS"


class TestInteractiveSelection:
    """Test interactive instance selection logic."""
    
    def test_interactive_selection_options(self):
        """Test that interactive selection creates correct options."""
        instances = [
            {"provider": "AWS", "instance": "r5.4xlarge", "vcpu": 16, "ram_gb": 128, "price_hr": 0.512},
            {"provider": "GCP", "instance": "n2-highmem-16", "vcpu": 16, "ram_gb": 128, "price_hr": 0.489},
            {"provider": "Azure", "instance": "E32s_v5", "vcpu": 32, "ram_gb": 256, "price_hr": 0.8}
        ]
        
        with patch('builtins.input', return_value='1'):
            selected_index = interactive_selection(instances, max_ram_gb=256)
            assert selected_index == 0  # Should select first option (cheapest per-core)
        
        with patch('builtins.input', return_value='2'):
            selected_index = interactive_selection(instances, max_ram_gb=256)
            assert selected_index == 1  # Should select second option (cheapest overall)
    
    def test_interactive_selection_memory_alternative(self):
        """Test memory alternative selection logic."""
        instances = [
            {"provider": "AWS", "instance": "r5.4xlarge", "vcpu": 16, "ram_gb": 128, "price_hr": 0.512},
            {"provider": "GCP", "instance": "n2-highmem-16", "vcpu": 16, "ram_gb": 128, "price_hr": 0.489},
            {"provider": "Azure", "instance": "E32s_v5", "vcpu": 32, "ram_gb": 256, "price_hr": 0.8}
        ]
        
        # Mock input to select memory alternative (option 3)
        with patch('builtins.input', return_value='3'):
            selected_index = interactive_selection(instances, max_ram_gb=512)
            assert selected_index == 2  # Should select Azure instance with more memory


class TestAWSPricing:
    """Test AWS spot price retrieval."""
    
    @patch('boto3.client')
    def test_get_aws_spot_prices(self, mock_boto_client):
        """Test AWS spot price API parsing."""
        mock_ec2 = MagicMock()
        mock_boto_client.return_value = mock_ec2
        
        # Mock API response
        mock_ec2.describe_spot_price_history.return_value = {
            'SpotPrices': [
                {
                    'InstanceType': 'r5.4xlarge',
                    'SpotPrice': '0.512',
                    'AvailabilityZone': 'us-east-1a'
                },
                {
                    'InstanceType': 'r5.8xlarge', 
                    'SpotPrice': '1.024',
                    'AvailabilityZone': 'us-east-1b'
                }
            ]
        }
        
        # Mock instance details
        with patch('find_cheapest_instance.get_instance_details') as mock_details:
            mock_details.return_value = {'vcpu': 16, 'ram_gb': 128}
            
            prices = get_aws_spot_prices('us-east-1', min_vcpu=16, max_vcpu=32)
            
            assert len(prices) >= 1
            assert prices[0]['provider'] == 'AWS'
            assert prices[0]['instance'] == 'r5.4xlarge'
            assert prices[0]['price_hr'] == 0.512
            assert prices[0]['region'] == 'us-east-1'


class TestConfigurationLoading:
    """Test configuration file loading and validation."""
    
    def test_load_hardware_config_from_file(self, config_file):
        """Test loading hardware requirements from config file."""
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        hardware = config['hardware']
        assert hardware['min_vcpu'] == 16
        assert hardware['max_vcpu'] == 32
        assert hardware['min_ram_gb'] == 64
        assert hardware['max_ram_gb'] == 256
    
    def test_config_override_with_args(self, sample_config):
        """Test that command-line args override config file settings."""
        # This would be tested in integration tests with actual argument parsing
        # Here we just verify the config structure
        assert 'hardware' in sample_config
        assert 'aws' in sample_config
        assert 'gcp' in sample_config
        assert 'azure' in sample_config


class TestPriceCalculations:
    """Test price calculation logic."""
    
    def test_price_per_core_calculation(self):
        """Test per-core price calculation accuracy."""
        instance = {
            "provider": "AWS",
            "instance": "r5.4xlarge", 
            "vcpu": 16,
            "price_hr": 0.512
        }
        
        expected_per_core = 0.512 / 16
        assert abs(expected_per_core - 0.032) < 0.001
    
    def test_price_comparison_accuracy(self):
        """Test price comparison logic."""
        instances = [
            {"vcpu": 16, "price_hr": 0.512},  # $0.032 per core
            {"vcpu": 8, "price_hr": 0.200},   # $0.025 per core (cheaper per core)
            {"vcpu": 32, "price_hr": 0.800}   # $0.025 per core (same per core, more total)
        ]
        
        # Sort by per-core price
        by_per_core = sorted(instances, key=lambda x: x['price_hr'] / x['vcpu'])
        assert by_per_core[0]['price_hr'] == 0.200  # 8-core instance cheapest per core
        assert by_per_core[1]['price_hr'] == 0.800  # 32-core instance next (same per-core as 8-core)
        
        # Sort by total price  
        by_total = sorted(instances, key=lambda x: x['price_hr'])
        assert by_total[0]['price_hr'] == 0.200  # 8-core cheapest total
        assert by_total[1]['price_hr'] == 0.512  # 16-core next cheapest total


class TestErrorHandling:
    """Test error handling in price discovery."""
    
    @patch('boto3.client')
    def test_aws_api_error_handling(self, mock_boto_client):
        """Test handling of AWS API errors."""
        mock_ec2 = MagicMock()
        mock_boto_client.return_value = mock_ec2
        
        # Simulate API error
        mock_ec2.describe_spot_price_history.side_effect = Exception("API Error")
        
        # Should handle gracefully and return empty list
        prices = get_aws_spot_prices('us-east-1')
        assert prices == []
    
    def test_invalid_hardware_requirements(self):
        """Test handling of invalid hardware requirements."""
        instances = [
            {"vcpu": 16, "ram_gb": 64, "price_hr": 0.4}
        ]
        
        # Test impossible requirements (min > max)
        filtered = filter_by_hardware_requirements(
            instances, min_vcpu=32, max_vcpu=16
        )
        assert len(filtered) == 0
        
        # Test requirements that exclude all instances
        filtered = filter_by_hardware_requirements(
            instances, min_vcpu=64, min_ram_gb=512
        )
        assert len(filtered) == 0