#!/bin/bash
# Setup rclone configuration for Google Drive access
set -e

echo "Setting up rclone configuration..."

# Create rclone config directory
mkdir -p ~/.config/rclone

# Try to get rclone config from various cloud secret managers
if [ -n "$AWS_DEFAULT_REGION" ] && command -v aws >/dev/null 2>&1; then
    echo "Attempting to retrieve rclone config from AWS Secrets Manager..."
    
    SECRET_NAME="${RCLONE_SECRET_NAME:-rclone_config_secret}"
    
    if aws secretsmanager get-secret-value \
        --secret-id "$SECRET_NAME" \
        --query SecretString \
        --output text > ~/.config/rclone/rclone.conf 2>/dev/null; then
        echo "Successfully retrieved rclone config from AWS Secrets Manager"
    else
        echo "Warning: Could not retrieve rclone config from AWS Secrets Manager"
    fi

elif command -v gcloud >/dev/null 2>&1; then
    echo "Attempting to retrieve rclone config from GCP Secret Manager..."
    
    SECRET_NAME="${RCLONE_SECRET_NAME:-rclone_config_secret}"
    
    if gcloud secrets versions access latest \
        --secret="$SECRET_NAME" > ~/.config/rclone/rclone.conf 2>/dev/null; then
        echo "Successfully retrieved rclone config from GCP Secret Manager"
    else
        echo "Warning: Could not retrieve rclone config from GCP Secret Manager"
    fi

elif command -v az >/dev/null 2>&1; then
    echo "Attempting to retrieve rclone config from Azure Key Vault..."
    
    VAULT_NAME="${KEY_VAULT_NAME:-cloud-scheduler-vault}"
    SECRET_NAME="${RCLONE_SECRET_NAME:-rclone-config-secret}"
    
    if az keyvault secret show \
        --vault-name "$VAULT_NAME" \
        --name "$SECRET_NAME" \
        --query value -o tsv > ~/.config/rclone/rclone.conf 2>/dev/null; then
        echo "Successfully retrieved rclone config from Azure Key Vault"
    else
        echo "Warning: Could not retrieve rclone config from Azure Key Vault"
    fi
fi

# Check if config file exists and is not empty
if [ -s ~/.config/rclone/rclone.conf ]; then
    echo "Rclone configuration loaded successfully"
    
    # Test rclone connectivity (but don't fail if it doesn't work)
    if rclone listremotes | grep -q "gdrive"; then
        echo "Google Drive remote 'gdrive' found in configuration"
    else
        echo "Warning: No 'gdrive' remote found in rclone configuration"
        echo "Available remotes:"
        rclone listremotes || echo "No remotes configured"
    fi
else
    echo "Warning: No rclone configuration found"
    echo "Google Drive sync will not be available"
    
    # Create a dummy config to prevent rclone errors
    cat > ~/.config/rclone/rclone.conf << EOF
# Dummy configuration - Google Drive sync disabled
[dummy]
type = local
EOF
fi

echo "Rclone setup completed"