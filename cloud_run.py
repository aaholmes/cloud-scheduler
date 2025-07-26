#!/usr/bin/env python3
"""
Cloud Run - Unified interface for running cloud jobs with S3 staging.
Uploads local files to S3, launches spot instance, and manages the job lifecycle.
"""
import argparse
import boto3
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List
from job_manager import get_job_manager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CloudJobManager:
    """Manages cloud job submission with S3 staging."""
    
    def __init__(self, s3_bucket: str, config_file: str = "config.json"):
        self.s3_bucket = s3_bucket
        self.s3_client = boto3.client('s3')
        self.job_id = str(uuid.uuid4())[:8]
        
        # Load configuration
        self.config = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                self.config = json.load(f)
    
    def upload_job_files(self, job_dir: str, exclude_patterns: List[str] = None) -> str:
        """Upload job directory to S3."""
        if exclude_patterns is None:
            exclude_patterns = ['*.pyc', '__pycache__', '.git', '*.log']
        
        s3_prefix = f"{self.job_id}/input/"
        uploaded_files = []
        
        logger.info(f"Uploading files from {job_dir} to s3://{self.s3_bucket}/{s3_prefix}")
        
        job_path = Path(job_dir)
        for file_path in job_path.rglob('*'):
            if file_path.is_file():
                # Check if file matches exclude patterns
                exclude = False
                for pattern in exclude_patterns:
                    if file_path.match(pattern):
                        exclude = True
                        break
                
                if not exclude:
                    relative_path = file_path.relative_to(job_path)
                    s3_key = f"{s3_prefix}{relative_path}"
                    
                    logger.info(f"Uploading {relative_path} to {s3_key}")
                    self.s3_client.upload_file(str(file_path), self.s3_bucket, s3_key)
                    uploaded_files.append(str(relative_path))
        
        logger.info(f"Uploaded {len(uploaded_files)} files to S3")
        return f"s3://{self.s3_bucket}/{s3_prefix}"
    
    def create_job_metadata(self, job_config: Dict[str, Any], s3_path: str) -> Dict[str, Any]:
        """Create metadata for the job including S3 paths and configuration."""
        metadata = {
            'job_id': self.job_id,
            's3_input_path': s3_path,
            's3_bucket': self.s3_bucket,
            'gdrive_path': job_config.get('gdrive_path', f'shci_jobs/{self.job_id}'),
            'shci_executable': job_config.get('shci_executable', './shci_program'),
            'basis_set': job_config.get('basis_set', 'aug-cc-pVDZ'),
            'calculation_type': job_config.get('calculation_type', 'shci'),
            'timestamp': time.strftime('%Y-%m-%d_%H-%M-%S')
        }
        
        # Add any custom environment variables
        if 'environment' in job_config:
            metadata['environment'] = job_config['environment']
        
        return metadata
    
    def launch_job(self, provider: str, instance_type: str, region: str, 
                   job_dir: str, job_config: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
        """Upload files to S3 and launch the job on specified instance."""
        
        # Upload files to S3 (unless dry run)
        if not dry_run:
            s3_path = self.upload_job_files(job_dir, job_config.get('exclude_patterns'))
        else:
            s3_path = f"s3://{self.s3_bucket}/{self.job_id}/input/"
            logger.info(f"[DRY RUN] Would upload files from {job_dir} to {s3_path}")
        
        # Create job metadata
        metadata = self.create_job_metadata(job_config, s3_path)
        
        if not dry_run:
            # Save metadata to S3
            metadata_key = f"{self.job_id}/metadata.json"
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=metadata_key,
                Body=json.dumps(metadata, indent=2),
                ContentType='application/json'
            )
            logger.info(f"Job metadata saved to s3://{self.s3_bucket}/{metadata_key}")
        else:
            logger.info(f"[DRY RUN] Would save metadata to s3://{self.s3_bucket}/{self.job_id}/metadata.json")
            logger.info(f"[DRY RUN] Metadata preview:\n{json.dumps(metadata, indent=2)}")
        
        # Update bootstrap script with job-specific environment variables
        env_vars = {
            'JOB_ID': self.job_id,
            'S3_BUCKET': self.s3_bucket,
            'S3_INPUT_PATH': s3_path,
            'GDRIVE_PATH': metadata['gdrive_path'],
            'SHCI_EXECUTABLE': metadata['shci_executable'],
            'BASIS_SET': metadata['basis_set']
        }
        
        # Add Docker image if specified
        if job_config.get('docker_image'):
            env_vars['DOCKER_IMAGE'] = job_config['docker_image']
        
        # Add custom environment variables
        if 'environment' in metadata:
            env_vars.update(metadata['environment'])
        
        # Choose bootstrap script based on Docker usage
        if job_config.get('use_docker', False):
            bootstrap_script_name = 'bootstrap-docker.sh'
        else:
            bootstrap_script_name = 'bootstrap.sh'
        
        # Create modified bootstrap script with environment variables
        bootstrap_content = self._create_custom_bootstrap(env_vars, bootstrap_script_name)
        
        # Save custom bootstrap script
        bootstrap_path = f"/tmp/bootstrap_{self.job_id}.sh"
        with open(bootstrap_path, 'w') as f:
            f.write(bootstrap_content)
        os.chmod(bootstrap_path, 0o755)
        
        if not dry_run:
            # Initialize job manager and create job record
            jm = get_job_manager()
            
            # Create initial job record
            initial_job_config = {
                's3_bucket': self.s3_bucket,  
                's3_input_path': s3_path,
                'gdrive_path': metadata['gdrive_path'],
                'basis_set': metadata['basis_set'],
                'price_per_hour': 0.0  # Will be updated after launch
            }
            
            initial_launch_result = {
                'status': 'launching',
                'provider': provider,
                'instance_type': instance_type,
                'region': region,
                'job_id': self.job_id
            }
            
            # Create job record
            if not jm.create_job(self.job_id, initial_job_config, initial_launch_result):
                logger.error("Failed to create job record in database")
                return {'status': 'failed', 'error': 'Database error'}
        else:
            logger.info(f"[DRY RUN] Would create job record in database for job {self.job_id}")
            logger.info(f"[DRY RUN] Provider: {provider}, Instance: {instance_type}, Region: {region}")
        
        if dry_run:
            # In dry run mode, just show what would be launched
            logger.info(f"[DRY RUN] Would launch instance with command:")
            launch_cmd = [
                sys.executable, 'launch_job.py',
                '--provider', provider,
                '--instance', instance_type,
                '--region', region,
                '--config', 'config.json'
            ]
            logger.info(f"[DRY RUN] Command: {' '.join(launch_cmd)}")
            logger.info(f"[DRY RUN] Bootstrap script would be created at: {bootstrap_path}")
            
            # Show bootstrap script preview
            with open(bootstrap_path, 'r') as f:
                bootstrap_preview = f.read()
            logger.info(f"[DRY RUN] Bootstrap script preview (first 500 chars):")
            logger.info(bootstrap_preview[:500] + "..." if len(bootstrap_preview) > 500 else bootstrap_preview)
            
            # Clean up temp files
            if os.path.exists(bootstrap_path):
                os.remove(bootstrap_path)
            
            # Return mock successful result
            mock_result = {
                'status': 'dry_run_success',
                'job_id': self.job_id,
                'provider': provider,
                'instance_type': instance_type,
                'region': region,
                's3_path': s3_path,
                'gdrive_path': metadata['gdrive_path'],
                'message': 'Dry run completed successfully - no instance was launched'
            }
            
            return mock_result
        
        # Normal launch process (not dry run)
        # Launch instance using existing launch_job.py
        launch_cmd = [
            sys.executable, 'launch_job.py',
            '--provider', provider,
            '--instance', instance_type,
            '--region', region,
            '--config', 'config.json'
        ]
        
        # Temporarily replace bootstrap.sh with our custom version
        import shutil
        original_bootstrap = None
        if os.path.exists('bootstrap.sh'):
            original_bootstrap = 'bootstrap.sh.bak'
            shutil.move('bootstrap.sh', original_bootstrap)
        
        shutil.copy(bootstrap_path, 'bootstrap.sh')
        
        try:
            # Run launch command
            import subprocess
            result = subprocess.run(launch_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info("Instance launched successfully")
                
                # Parse launch result
                with open('launch_result.json', 'r') as f:
                    launch_result = json.load(f)
                
                # Add job metadata to launch result
                launch_result['job_id'] = self.job_id
                launch_result['s3_path'] = s3_path
                launch_result['gdrive_path'] = metadata['gdrive_path']
                
                # Update job record with launch details
                job_update_data = {
                    'instance_id': launch_result.get('instance_id'),
                    'public_ip': launch_result.get('public_ip'),
                    'private_ip': launch_result.get('private_ip')
                }
                
                jm.update_job_status(self.job_id, 'launched', job_update_data)
                
                # Save enhanced result
                result_path = f"job_{self.job_id}_launch.json"
                with open(result_path, 'w') as f:
                    json.dump(launch_result, f, indent=2)
                
                logger.info(f"Job launch details saved to {result_path}")
                logger.info(f"Job {self.job_id} recorded in database")
                
                return launch_result
            else:
                logger.error(f"Failed to launch instance: {result.stderr}")
                
                # Update job status to failed
                jm.update_job_status(self.job_id, 'failed', {
                    'error_message': result.stderr
                })
                
                return {'status': 'failed', 'error': result.stderr}
        
        finally:
            # Restore original bootstrap.sh
            if original_bootstrap and os.path.exists(original_bootstrap):
                shutil.move(original_bootstrap, 'bootstrap.sh')
            
            # Clean up temp files
            if os.path.exists(bootstrap_path):
                os.remove(bootstrap_path)
    
    def _create_custom_bootstrap(self, env_vars: Dict[str, str], bootstrap_script: str = 'bootstrap.sh') -> str:
        """Create a custom bootstrap script with job-specific variables."""
        # Read the original bootstrap script
        with open(bootstrap_script, 'r') as f:
            bootstrap_content = f.read()
        
        # Insert environment variables at the beginning
        env_section = "# Job-specific environment variables\n"
        for key, value in env_vars.items():
            env_section += f'export {key}="{value}"\n'
        env_section += "\n"
        
        # Insert after the shebang and initial comments
        lines = bootstrap_content.split('\n')
        insert_index = 0
        for i, line in enumerate(lines):
            if line.strip() and not line.startswith('#'):
                insert_index = i
                break
        
        lines.insert(insert_index, env_section)
        
        # Modify the S3 download section
        modified_content = '\n'.join(lines)
        
        # Add S3 download command after system setup
        s3_download = '''
# --- Download Input Files from S3 ---
echo "Downloading input files from S3..."
cd $HOME_DIR
mkdir -p job_input
cd job_input
aws s3 sync "${S3_INPUT_PATH}" . --exclude "*.log"
cd $HOME_DIR

# Copy run_calculation.py if it exists in job input
if [ -f job_input/run_calculation.py ]; then
    cp job_input/run_calculation.py $HOME_DIR/
fi
'''
        
        # Insert S3 download before the code cloning section
        modified_content = modified_content.replace(
            "# --- Get and Build Code ---",
            s3_download + "\n# --- Get and Build Code ---"
        )
        
        # Update the rclone sync command to exclude FCIDUMP
        modified_content = modified_content.replace(
            'rclone sync "$OUTPUT_DIR" "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}"',
            'rclone sync "$OUTPUT_DIR" "${GDRIVE_REMOTE}:${GDRIVE_PATH}" --exclude "FCIDUMP" --exclude "*.tmp"'
        )
        
        # Update the output directory path to use GDRIVE_PATH
        modified_content = modified_content.replace(
            'GDRIVE_DEST_DIR="${GDRIVE_DEST_DIR:-shci_project/results_$(date +%Y-%m-%d_%H-%M-%S)}"',
            'GDRIVE_PATH="${GDRIVE_PATH:-shci_project/results_$(date +%Y-%m-%d_%H-%M-%S)}"'
        )
        
        # Replace all instances of GDRIVE_DEST_DIR with GDRIVE_PATH
        modified_content = modified_content.replace('GDRIVE_DEST_DIR', 'GDRIVE_PATH')
        
        return modified_content


def main():
    """Main entry point for cloud job submission."""
    parser = argparse.ArgumentParser(description="Submit cloud jobs with S3 staging")
    
    # Required arguments
    parser.add_argument("job_dir", help="Directory containing job input files")
    parser.add_argument("--s3-bucket", required=True, help="S3 bucket for staging files")
    
    # Instance selection
    parser.add_argument("--provider", choices=['AWS', 'GCP', 'Azure'], 
                       help="Cloud provider (default: use cheapest from spot_prices.json)")
    parser.add_argument("--instance", help="Instance type")
    parser.add_argument("--region", help="Cloud region")
    parser.add_argument("--from-spot-prices", action="store_true",
                       help="Use cheapest instance from spot_prices.json")
    parser.add_argument("--index", type=int, default=0,
                       help="Index from spot_prices.json (default: 0)")
    
    # Job configuration
    parser.add_argument("--basis", default="aug-cc-pVDZ", help="Basis set for calculation")
    parser.add_argument("--gdrive-path", help="Google Drive path for results")
    parser.add_argument("--shci-executable", default="./shci_program", 
                       help="Path to SHCI executable on instance")
    parser.add_argument("--exclude", nargs="+", 
                       help="Additional file patterns to exclude from upload")
    
    # Hardware requirements (passed to find_cheapest_instance.py)
    parser.add_argument("--min-vcpu", type=int,
                       help="Minimum vCPUs required")
    parser.add_argument("--max-vcpu", type=int,
                       help="Maximum vCPUs to consider")
    parser.add_argument("--min-ram", type=int,
                       help="Minimum RAM in GB")
    parser.add_argument("--max-ram", type=int,
                       help="Maximum RAM in GB")
    
    # Docker options
    parser.add_argument("--docker", action="store_true",
                       help="Use Docker containerized deployment")
    parser.add_argument("--docker-image", 
                       help="Docker image to use (default: from config or ghcr.io/cloud-scheduler/quantum-chemistry:latest)")
    
    # Configuration
    parser.add_argument("--config", default="config.json", help="Configuration file")
    
    # Dry run mode
    parser.add_argument("--dry-run", action="store_true",
                       help="Perform all steps except launching the actual instance")
    
    args = parser.parse_args()
    
    # Validate job directory
    if not os.path.isdir(args.job_dir):
        logger.error(f"Job directory not found: {args.job_dir}")
        sys.exit(1)
    
    # Determine instance details
    if args.from_spot_prices or not all([args.provider, args.instance, args.region]):
        # Check if we need to run find_cheapest_instance.py first
        if not os.path.exists('spot_prices.json') or hasattr(args, 'hardware_changed'):
            logger.info("Running instance discovery with current hardware requirements...")
            
            # Build find_cheapest_instance.py command
            find_cmd = [sys.executable, 'find_cheapest_instance.py', '--config', args.config]
            
            # Add hardware requirements if specified
            if args.min_vcpu:
                find_cmd.extend(['--min-vcpu', str(args.min_vcpu)])
            if args.max_vcpu:
                find_cmd.extend(['--max-vcpu', str(args.max_vcpu)])
            if args.min_ram:
                find_cmd.extend(['--min-ram', str(args.min_ram)])
            if args.max_ram:
                find_cmd.extend(['--max-ram', str(args.max_ram)])
            
            # Run in non-interactive mode
            find_cmd.append('--no-interactive')
            
            import subprocess
            result = subprocess.run(find_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Failed to find instances: {result.stderr}")
                sys.exit(1)
        
        # Load from spot_prices.json
        if not os.path.exists('spot_prices.json'):
            logger.error("spot_prices.json not found. Run find_cheapest_instance.py first.")
            sys.exit(1)
        
        with open('spot_prices.json', 'r') as f:
            spot_prices = json.load(f)
        
        if args.index >= len(spot_prices):
            logger.error(f"Index {args.index} out of range. File has {len(spot_prices)} entries.")
            sys.exit(1)
        
        selected = spot_prices[args.index]
        provider = selected['provider']
        instance = selected['instance']
        region = selected['region']
        
        logger.info(f"Selected from spot_prices.json: {provider} {instance} in {region} "
                   f"at ${selected['price_hr']:.4f}/hour")
    else:
        provider = args.provider
        instance = args.instance
        region = args.region
    
    # Create job configuration
    job_config = {
        'basis_set': args.basis,
        'shci_executable': args.shci_executable,
        'exclude_patterns': args.exclude or [],
        'use_docker': args.docker
    }
    
    # Add Docker image if specified
    if args.docker_image:
        job_config['docker_image'] = args.docker_image
    elif args.docker:
        # Use default Docker image
        job_config['docker_image'] = 'ghcr.io/cloud-scheduler/quantum-chemistry:latest'
    
    if args.gdrive_path:
        job_config['gdrive_path'] = args.gdrive_path
    
    # Initialize job manager
    manager = CloudJobManager(args.s3_bucket, args.config)
    
    # Launch the job
    if args.dry_run:
        logger.info(f"=== DRY RUN MODE - NO INSTANCE WILL BE LAUNCHED ===")
        logger.info(f"Preparing dry run for job {manager.job_id}")
    else:
        logger.info(f"Launching job {manager.job_id}")
    
    result = manager.launch_job(provider, instance, region, args.job_dir, job_config, dry_run=args.dry_run)
    
    if result.get('status') == 'dry_run_success':
        logger.info(f"\n=== DRY RUN COMPLETED SUCCESSFULLY ===")
        logger.info(f"Job ID: {manager.job_id}")
        logger.info(f"Provider: {result['provider']}")
        logger.info(f"Instance Type: {result['instance_type']}")
        logger.info(f"Region: {result['region']}")
        logger.info(f"S3 Path: {result['s3_path']}")
        logger.info(f"Google Drive Path: {result['gdrive_path']}")
        logger.info(f"\nTo actually launch this job, run the same command without --dry-run")
    elif result.get('status') == 'launched' or result.get('status') != 'failed':
        logger.info(f"\nJob {manager.job_id} launched successfully!")
        logger.info(f"Input files: s3://{args.s3_bucket}/{manager.job_id}/input/")
        logger.info(f"Results will sync to: gdrive:{job_config.get('gdrive_path', f'shci_jobs/{manager.job_id}')}")
        logger.info(f"\nMonitor progress in Google Drive (syncs every 5 minutes)")
    else:
        logger.error(f"Failed to launch job: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()