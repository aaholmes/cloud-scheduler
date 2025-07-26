# Cloud Scheduler Setup Instructions

## Prerequisites

### 1. Cloud Provider Accounts
- **AWS**: Active account with billing enabled
- **GCP**: Active project with billing enabled  
- **Azure**: Active subscription

### 2. Local Development Environment

Install required CLIs:
```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Google Cloud SDK
curl https://sdk.cloud.google.com | bash

# Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

### 3. Python Dependencies

```bash
pip install -r requirements.txt
```

## Cloud Provider Setup

### AWS Setup

#### S3 Bucket Setup (Required for Job Staging)

1. Create S3 bucket for job staging:
```bash
# Create bucket (use your own unique name)
aws s3 mb s3://my-shci-jobs --region us-east-1

# Enable versioning (optional but recommended)
aws s3api put-bucket-versioning \
  --bucket my-shci-jobs \
  --versioning-configuration Status=Enabled

# Set lifecycle policy to auto-delete old files (optional)
cat > lifecycle.json << EOF
{
  "Rules": [{
    "ID": "DeleteOldJobFiles",
    "Status": "Enabled",
    "Filter": {"Prefix": ""},
    "Expiration": {"Days": 30}
  }]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
  --bucket my-shci-jobs \
  --lifecycle-configuration file://lifecycle.json
```

2. Update IAM role to include S3 access:
```bash
# Create S3 policy
cat > s3-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject",
      "s3:ListBucket"
    ],
    "Resource": [
      "arn:aws:s3:::my-shci-jobs/*",
      "arn:aws:s3:::my-shci-jobs"
    ]
  }]
}
EOF

# Attach to role
aws iam put-role-policy \
  --role-name cloud-scheduler-role \
  --policy-name S3AccessPolicy \
  --policy-document file://s3-policy.json
```

### AWS General Setup

1. Configure AWS credentials:
```bash
aws configure
```

2. Create IAM role for instances:
```bash
aws iam create-role --role-name cloud-scheduler-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policy for Secrets Manager access
aws iam attach-role-policy --role-name cloud-scheduler-role \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite

# Create instance profile
aws iam create-instance-profile --instance-profile-name cloud-scheduler-profile
aws iam add-role-to-instance-profile \
  --instance-profile-name cloud-scheduler-profile \
  --role-name cloud-scheduler-role
```

3. Store rclone config in Secrets Manager:
```bash
aws secretsmanager create-secret \
  --name rclone_config_secret \
  --secret-string "$(cat ~/.config/rclone/rclone.conf)"
```

### GCP Setup

1. Authenticate and set project:
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

2. Enable required APIs:
```bash
gcloud services enable compute.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable cloudbilling.googleapis.com
```

3. Create service account:
```bash
gcloud iam service-accounts create cloud-scheduler \
  --display-name="Cloud Scheduler Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:cloud-scheduler@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:cloud-scheduler@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

4. Store rclone config in Secret Manager:
```bash
gcloud secrets create rclone_config_secret \
  --data-file="$HOME/.config/rclone/rclone.conf"
```

### Azure Setup

1. Login to Azure:
```bash
az login
```

2. Create resource group:
```bash
az group create --name cloud-scheduler-rg --location eastus
```

3. Create Key Vault:
```bash
az keyvault create \
  --name cloud-scheduler-vault \
  --resource-group cloud-scheduler-rg \
  --location eastus
```

4. Store rclone config:
```bash
az keyvault secret set \
  --vault-name cloud-scheduler-vault \
  --name rclone-config-secret \
  --file ~/.config/rclone/rclone.conf
```

## Rclone Configuration

1. Install rclone locally:
```bash
curl https://rclone.org/install.sh | sudo bash
```

2. Configure Google Drive:
```bash
rclone config

# Follow prompts:
# - New remote
# - Name: gdrive
# - Storage: drive
# - Follow OAuth flow
```

3. Test configuration:
```bash
rclone ls gdrive:
```

## Configuration File

Create `config.json` with your settings:

```json
{
  "aws": {
    "key_name": "your-ec2-keypair",
    "security_group": "cloud-scheduler-sg",
    "iam_role": "cloud-scheduler-role",
    "max_price": 5.0,
    "disk_size_gb": 100
  },
  "gcp": {
    "project_id": "your-project-id",
    "service_account_email": "cloud-scheduler@your-project-id.iam.gserviceaccount.com",
    "disk_size_gb": 100
  },
  "azure": {
    "subscription_id": "your-subscription-id",
    "resource_group": "cloud-scheduler-rg",
    "admin_password": "ComplexPassword123!",
    "disk_size_gb": 100
  }
}
```

## Usage

### 1. Find cheapest instances:
```bash
python find_cheapest_instance.py
```

This will:
- Query spot prices across all providers
- Filter by hardware requirements (16-32 vCPUs, 64-256GB RAM)
- Save results to `spot_prices.json`

### 2. Submit a job with S3 staging (Recommended):

The `cloud_run.py` script handles the complete workflow:

```bash
# Submit job using cheapest instance
python cloud_run.py /path/to/job/files \
  --s3-bucket my-shci-jobs \
  --from-spot-prices

# Submit with specific instance
python cloud_run.py /path/to/job/files \
  --s3-bucket my-shci-jobs \
  --provider AWS \
  --instance r7i.8xlarge \
  --region us-east-1

# Custom options
python cloud_run.py /path/to/job/files \
  --s3-bucket my-shci-jobs \
  --from-spot-prices \
  --basis cc-pVTZ \
  --gdrive-path "calculations/water_dimer_$(date +%Y%m%d)" \
  --exclude "*.bak" "*.old"
```

This will:
1. Upload your job files to S3 (excluding FCIDUMP files)
2. Launch the spot instance with custom bootstrap
3. Instance downloads files from S3
4. Runs calculation
5. Syncs results to Google Drive (excluding FCIDUMP)
6. Terminates automatically

### 3. Direct instance launch (Advanced):

Option A - Launch the cheapest instance:
```bash
python launch_job.py --from-file spot_prices.json --index 0
```

Option B - Launch specific instance:
```bash
python launch_job.py --provider AWS --instance r7i.8xlarge --region us-east-1
```

### 4. Monitor progress:

The instance will:
- Install dependencies automatically
- Run the calculation
- Sync results to Google Drive every 5 minutes
- Terminate automatically when complete

Check your Google Drive folder for results:
- `shci_project/results_YYYY-MM-DD_HH-MM-SS/`

## Environment Variables

You can override bootstrap script settings:

```bash
export SHCI_REPO_URL="https://github.com/yourusername/your-shci-repo.git"
export GDRIVE_REMOTE="mydrive"
export GDRIVE_DEST_DIR="calculations/water_dimer"
```

## Troubleshooting

### AWS Issues
- Ensure your account has spot instance limits
- Check security group allows SSH (port 22)
- Verify IAM role has necessary permissions

### GCP Issues
- Enable billing for your project
- Check quota limits for your desired regions
- Ensure service account has proper permissions

### Azure Issues
- Verify subscription has sufficient quota
- Check resource group exists
- Ensure Key Vault access policies are configured

### Rclone Issues
- Test rclone locally first: `rclone ls gdrive:`
- Ensure OAuth tokens are fresh
- Check rclone.conf is properly formatted

## Security Notes

- Never commit credentials or config files to git
- Use IAM roles instead of access keys when possible
- Regularly rotate secrets
- Monitor your cloud spending