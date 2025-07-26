# Changelog

## [2024-01-26] - S3 Staging and FCIDUMP Exclusion

### Added
- `cloud_run.py` - New unified job submission interface with S3 staging
  - Uploads job files to S3 bucket before instance launch
  - Generates unique job IDs for tracking
  - Supports custom environment variables and configuration
- S3 bucket setup instructions in SETUP.md
- FCIDUMP exclusion from Google Drive syncs to save bandwidth/storage

### Changed
- Updated `bootstrap.sh` to exclude FCIDUMP and temporary files from rclone syncs
- Enhanced documentation to reflect S3 staging workflow
- Modified instance launch process to support job-specific configurations

### Benefits
- **Reliability**: S3 provides stable file transfer to ephemeral instances
- **Cost Savings**: FCIDUMP exclusion reduces Google Drive storage usage
- **Flexibility**: Easy to specify custom paths and configurations per job

## [Initial Release]

### Features
- Multi-cloud spot price discovery (AWS, GCP, Azure)
- Automated instance provisioning
- Quantum chemistry calculation support (SHCI/PySCF)
- Automatic result syncing to Google Drive
- Self-terminating instances for cost optimization