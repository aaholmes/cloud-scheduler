# **Detailed Implementation Plan for Automated Cloud Job Submission**

**Objective:** Create a set of scripts to find the cheapest spot instance across AWS, GCP, and Azure (and across types of instances and regions) that meets specified hardware requirements, launch a job on that instance, and have the instance run a quantum chemistry calculation, periodically syncing results to Google Drive before self-terminating.

**System Architecture:**

1.  **Local Machine:** Runs a Python script (`find_cheapest_instance.py`) to query cloud provider APIs for the best spot price. A second script (`launch_job.py`) then uses this information to launch the chosen instance.
2.  **Cloud Instance (Ephemeral):** A temporary spot VM that boots up, runs a startup script (`bootstrap.sh`), executes the main calculation (`run_calculation.py`), syncs results, and then shuts down.
3.  **Google Drive:** Acts as the persistent storage for output files, synced via `rclone`.

**Prerequisites (Setup required before running):**

1.  **Cloud Accounts:** Active accounts with billing enabled for AWS, GCP, and Azure.
2.  **Local SDKs/CLIs:** AWS CLI, Google Cloud SDK, and Azure CLI installed and configured on your laptop.
3.  **Python Libraries (Local):** `boto3` for AWS, `google-api-python-client` and `google-cloud-billing` for GCP, and `azure-identity` & `azure-mgmt-compute` for Azure.
4.  **`rclone` Configuration:** `rclone` must be configured on your local machine for Google Drive at least once to generate a `rclone.conf` file. This file contains the necessary authentication tokens.
5.  **Secure Storage for `rclone.conf`:** The contents of your local `rclone.conf` file should be stored securely in a secret manager (e.g., AWS Secrets Manager, GCP Secret Manager, or Azure Key Vault). This is the most secure way to provide credentials to the ephemeral cloud instance.
6.  **Code Repository:** Your SHCI code and the `run_calculation.py` script must be available in a Git repository (e.g., GitHub) that the cloud instance can clone.

-----

### **Component 1: Price-Checking Script**

This script queries the APIs of all three cloud providers to find the most cost-effective spot instance that meets the hardware requirements.

**File:** `find_cheapest_instance.py`
**Instructions for Claude Code:**

* Implement a function for each cloud provider (AWS, GCP, Azure) to fetch current spot prices.
* Use the specified vCPU and RAM ranges to filter the available instances.
* Normalize the prices by calculating a cost-per-hour to allow for direct comparison.
* The script should output a sorted list of the top 5 cheapest instances, including provider, instance name, region, vCPUs, RAM, and hourly spot price.

<!-- end list -->

```python
# find_cheapest_instance.py
import boto3
import requests
import json
from google.cloud import billing_v1

# --- Configuration ---
MIN_VCPU = 16
MAX_VCPU = 32
MIN_RAM_GB = 64
MAX_RAM_GB = 256

def get_aws_spot_prices():
    """Queries AWS for spot prices of memory-optimized instances."""
    print("Querying AWS...")
    instances =
    # Use a session to get available regions
    session = boto3.Session()
    regions = session.get_available_regions('ec2')

    for region in regions:
        try:
            # Boto3 client for each region
            client = boto3.client('ec2', region_name=region)
            # Filter for memory-optimized (r-series) and general purpose (m-series)
            paginator = client.get_paginator('describe_spot_price_history')
            pages = paginator.paginate(
                ProductDescriptions=['Linux/UNIX (Amazon VPC)'],
                Filters=[
                    {'Name': 'instance-type', 'Values': ['r*', 'm*']}
                ]
            )
            for page in pages:
                for price_info in page.get('SpotPriceHistory',):
                    # This part is simplified. A full implementation would need to
                    # call describe_instance_types to get vCPU/RAM info.
                    # For this plan, we'll hardcode a known good instance.
                    if price_info == 'r7i.8xlarge':
                        instances.append({
                            'provider': 'AWS',
                            'instance': price_info,
                            'region': price_info['AvailabilityZone'][:-1],
                            'price_hr': float(price_info),
                            'vcpu': 32,
                            'ram_gb': 256
                        })
        except Exception as e:
            # Some regions may not be enabled or have spot price history
            # print(f"Could not query AWS region {region}: {e}")
            pass
    return instances

def get_gcp_spot_prices():
    """Queries GCP for spot prices of memory-optimized instances."""
    # This is a conceptual example. The Cloud Billing API is complex.
    # A real implementation would need to parse the public SKU catalog.
    # See: https://cloud.google.com/billing/docs/how-to/get-pricing
    print("Querying GCP...")
    # Example data for a known good instance
    return
        'vcpu': 32,
        'ram_gb': 256
    }]

def get_azure_spot_prices():
    """Queries Azure for spot prices of memory-optimized instances."""
    # Uses the Azure Retail Prices API
    print("Querying Azure...")
    instances =
    api_url = "https://prices.azure.com/api/retail/prices"
    query = f"$filter=serviceName eq 'Virtual Machines' and priceType eq 'Spot' and contains(skuName, 'v5')"
    response = requests.get(f"{api_url}?{query}")
    if response.status_code == 200:
        data = response.json()
        for item in data.get('Items',):
            # This part is simplified. A full implementation would need to parse armSkuName
            # to get vCPU/RAM info from a separate API call or a mapping table.
            if 'E32s v5' in item.get('productName', ''):
                 instances.append({
                    'provider': 'Azure',
                    'instance': item,
                    'region': item,
                    'price_hr': item['retailPrice'],
                    'vcpu': 32,
                    'ram_gb': 256
                })
    return instances

if __name__ == "__main__":
    all_instances =
    all_instances.extend(get_aws_spot_prices())
    all_instances.extend(get_gcp_spot_prices())
    all_instances.extend(get_azure_spot_prices())

    # Filter based on hardware requirements
    filtered = [
        inst for inst in all_instances
        if MIN_VCPU <= inst['vcpu'] <= MAX_VCPU and MIN_RAM_GB <= inst['ram_gb'] <= MAX_RAM_GB
    ]

    # Sort by price
    sorted_instances = sorted(filtered, key=lambda x: x['price_hr'])

    print("\n--- Top 5 Cheapest Spot Instances ---")
    for inst in sorted_instances[:5]:
        print(
            f"{inst['provider']:<5} | {inst['instance']:<15} | {inst['region']:<15} | "
            f"vCPUs: {inst['vcpu']:<3} | RAM: {inst['ram_gb']:<4}GB | Price: ${inst['price_hr']:.4f}/hr"
        )

```

### **Component 2: Job Launch Script**

This script takes the details of the chosen instance and launches it with the appropriate startup script.

**File:** `launch_job.py`
**Instructions for Claude Code:**

* The script should take arguments for provider, instance type, region, etc.
* It must read the `bootstrap.sh` file from the local disk.
* Implement a function `launch_aws_spot` that uses `boto3`'s `request_spot_instances` method. The key is to pass the contents of `bootstrap.sh` to the `UserData` parameter.
* Provide placeholder functions for `launch_gcp_spot` and `launch_azure_spot` with comments explaining that they need to be implemented using their respective SDKs, passing the bootstrap script as startup metadata.

<!-- end list -->

```python
# launch_job.py
import boto3
import base64
import argparse

def launch_aws_spot(instance_type, region, key_name, security_group, ami_id):
    """Launches an AWS spot instance with a startup script."""
    try:
        with open("bootstrap.sh", "r") as f:
            bootstrap_script = f.read()

        ec2 = boto3.client("ec2", region_name=region)
        
        encoded_script = base64.b64encode(bootstrap_script.encode("utf-8")).decode("utf-8")

        print(f"Requesting AWS spot instance {instance_type} in {region}...")
        response = ec2.request_spot_instances(
            InstanceCount=1,
            LaunchSpecification={
                "ImageId": ami_id,
                "InstanceType": instance_type,
                "KeyName": key_name,
                "SecurityGroups": [security_group],
                "UserData": encoded_script,
            },
            Type="one-time",
        )
        print("Spot request sent successfully. Check AWS console for status.")
        return response
    except Exception as e:
        print(f"An error occurred with AWS: {e}")

def launch_gcp_spot(instance_type, region, project_id):
    # To be implemented using Google Cloud SDK
    # See: https://cloud.google.com/compute/docs/instances/create-start-instance
    print("GCP launch function not yet implemented.")
    pass

def launch_azure_spot(instance_type, region, resource_group):
    # To be implemented using Azure SDK for Python
    # See: https://learn.microsoft.com/en-us/azure/virtual-machines/windows/python-sdk-azure-get-started
    print("Azure launch function not yet implemented.")
    pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch a cloud compute job.")
    parser.add_argument("--provider", required=True, choices=, help="Cloud provider")
    parser.add_argument("--instance", required=True, help="Instance type (e.g., r7i.8xlarge)")
    parser.add_argument("--region", required=True, help="Cloud region (e.g., us-east-1)")
    # Add provider-specific arguments
    parser.add_argument("--aws_key_name", help="AWS EC2 Key Pair name")
    parser.add_argument("--aws_sg", help="AWS Security Group name")
    parser.add_argument("--aws_ami", default="ami-0c55b159cbfafe1f0", help="Amazon Linux 2 AMI ID")
    
    args = parser.parse_args()

    if args.provider == 'AWS':
        if not args.aws_key_name or not args.aws_sg:
            print("Error: --aws_key_name and --aws_sg are required for AWS.")
        else:
            launch_aws_spot(args.instance, args.region, args.aws_key_name, args.aws_sg, args.aws_ami)
    # Add logic for other providers here

```

### **Component 3: Cloud Instance Bootstrap Script**

This is the core automation script that runs on the remote instance upon startup.

**File:** `bootstrap.sh`
**Instructions for Claude Code:**

* The script must be a robust shell script (`#!/bin/bash`).
* It should install all necessary software: `git`, `python3-pip`, `pyscf`, and `rclone`.
* It must securely fetch the `rclone.conf` content from a secret manager and write it to the correct location (`~/.config/rclone/rclone.conf`).
* It should clone the Git repository containing the SHCI code and `run_calculation.py`.
* It must run the main Python calculation script in the background and capture its Process ID (PID).
* Implement a `while` loop that periodically (e.g., every 5 minutes) calls `rclone sync` to copy the contents of the output directory to a specified Google Drive folder. The loop should continue as long as the calculation process is running.
* After the calculation finishes, it must perform one final sync.
* Crucially, the script must end with `sudo shutdown -h now` to terminate the instance and stop billing.

<!-- end list -->

```bash
#!/bin/bash
# bootstrap.sh - Executed on the cloud instance at startup

# --- Configuration ---
# The name of the secret in AWS Secrets Manager containing your rclone.conf content
RCLONE_CONFIG_SECRET_NAME="rclone_config_secret"
# Your SHCI code repository
SHCI_REPO_URL="https://github.com/your_username/your_shci_repo.git"
# Your Google Drive remote name (as configured in rclone.conf) and destination folder
GDRIVE_REMOTE="gdrive_remote"
GDRIVE_DEST_DIR="shci_project/prelim_results_$(date +%Y-%m-%d_%H-%M-%S)"
# AWS Region for the secret
AWS_REGION="us-east-1" # Should match the instance's region

# --- System Setup ---
echo "Updating system and installing dependencies..."
sudo yum update -y
sudo yum install -y git python3-pip

# Install PySCF for integral generation
pip3 install pyscf

# Install rclone
curl https://rclone.org/install.sh | sudo bash

# --- Configure Rclone from Secrets Manager ---
echo "Configuring rclone..."
mkdir -p /home/ec2-user/.config/rclone
# Use the AWS CLI to fetch the secret and write it to the rclone config file
aws secretsmanager get-secret-value --secret-id $RCLONE_CONFIG_SECRET_NAME --region $AWS_REGION --query SecretString --output text > /home/ec2-user/.config/rclone/rclone.conf
chown -R ec2-user:ec2-user /home/ec2-user/.config

# --- Get and Build Code ---
echo "Cloning SHCI repository..."
cd /home/ec2-user
git clone $SHCI_REPO_URL
cd your_shci_repo # Change to your repo's directory name
# Add compilation steps for your SHCI code here if necessary
# e.g., make

# --- Run Calculation and Sync Results ---
OUTPUT_DIR="/home/ec2-user/shci_output"
mkdir -p $OUTPUT_DIR
chown -R ec2-user:ec2-user $OUTPUT_DIR

echo "Starting calculation in the background..."
# Run the main calculation script as the ec2-user
sudo -u ec2-user python3 run_calculation.py --basis "aug-cc-pVDZ" --output_dir $OUTPUT_DIR > $OUTPUT_DIR/calculation.log 2>&1 &
CALC_PID=$!

echo "Calculation running with PID $CALC_PID. Starting periodic sync to Google Drive."

# Periodically sync results to Google Drive while the calculation runs
while kill -0 $CALC_PID 2>/dev/null; do
    sleep 300 # Sync every 5 minutes
    echo "Syncing results to ${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}..."
    sudo -u ec2-user rclone sync $OUTPUT_DIR "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}" --create-empty-src-dirs
done

# --- Final Sync and Shutdown ---
echo "Calculation finished. Performing final sync..."
sudo -u ec2-user rclone sync $OUTPUT_DIR "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}" --create-empty-src-dirs

echo "Final sync complete. Shutting down instance."
sudo shutdown -h now

```

### **Component 4: On-Node Calculation Script**

This is the Python script that orchestrates the scientific part of the job on the cloud instance.

**File:** `run_calculation.py`
**Instructions for Claude Code:**

* The script should use `argparse` to handle command-line arguments (basis set, output directory, etc.).
* It must use the `pyscf` library to define the water dimer molecule, specify the basis set, and run a Hartree-Fock calculation.
* It needs to generate the `FCIDUMP` file, which contains the one- and two-electron integrals required by the SHCI program.
* It will use Python's `subprocess` module to execute the compiled SHCI binary, passing the path to the `FCIDUMP` file and other necessary parameters.
* All output from the SHCI program should be redirected to files within the specified output directory.

<!-- end list -->

```python
# run_calculation.py
import argparse
import os
import subprocess
from pyscf import gto, scf
from pyscf.tools import fcidump

def run_shci_calculation(basis, output_dir):
    """
    Generates integrals with PySCF and runs the SHCI executable.
    """
    print(f"Setting up water dimer calculation with basis: {basis}")

    # 1. Define the water dimer geometry (from literature)
    mol = gto.Mole()
    mol.atom = ['O', (-1.551007, -0.114520, 0.000000)],
        ['H', (-1.934259, 0.762503, 0.000000)],
        ['H', (-0.599677, 0.040712, 0.000000)],
        ['O', (1.350625, 0.111469, 0.000000)],
        ['H', (1.680398, -0.373741, -0.758561)],
        ['H', (1.680398, -0.373741, 0.758561)]
    mol.basis = basis
    mol.build()

    # 2. Run Hartree-Fock with PySCF
    print("Running Hartree-Fock...")
    mf = scf.RHF(mol).run()

    # 3. Generate FCIDUMP file with integrals
    fcidump_path = os.path.join(output_dir, 'FCIDUMP')
    print(f"Generating FCIDUMP file at: {fcidump_path}")
    with open(fcidump_path, 'w') as f:
        fcidump.from_scf(mf, f)

    # 4. Execute the SHCI program
    # Assumes your compiled SHCI executable is named 'shci_program'
    # and is in the parent directory.
    shci_executable = './shci_program' # Adjust path as needed
    shci_output_file = os.path.join(output_dir, 'shci.out')
    
    shci_command =

    print(f"Executing SHCI command: {' '.join(shci_command)}")
    with open(shci_output_file, 'w') as out_f:
        process = subprocess.run(
            shci_command,
            stdout=out_f,
            stderr=subprocess.STDOUT,
            text=True
        )

    if process.returncode == 0:
        print("SHCI calculation completed successfully.")
    else:
        print(f"SHCI calculation failed with return code {process.returncode}.")
        print(f"Check log file: {shci_output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an SHCI calculation.")
    parser.add_argument("--basis", required=True, help="Basis set, e.g., 'aug-cc-pVDZ'")
    parser.add_argument("--output_dir", required=True, help="Directory to save output files.")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        
    run_shci_calculation(args.basis, args.output_dir)

```