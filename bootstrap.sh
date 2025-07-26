#!/bin/bash
# bootstrap.sh - Executed on the cloud instance at startup

set -e  # Exit on error
set -x  # Print commands for debugging

# --- Configuration ---
# These can be overridden by environment variables
RCLONE_CONFIG_SECRET_NAME="${RCLONE_CONFIG_SECRET_NAME:-rclone_config_secret}"
SHCI_REPO_URL="${SHCI_REPO_URL:-https://github.com/your_username/your_shci_repo.git}"
GDRIVE_REMOTE="${GDRIVE_REMOTE:-gdrive}"
GDRIVE_DEST_DIR="${GDRIVE_DEST_DIR:-shci_project/results_$(date +%Y-%m-%d_%H-%M-%S)}"

# Detect cloud provider
if [ -f /sys/hypervisor/uuid ] && grep -q ^ec2 /sys/hypervisor/uuid; then
    CLOUD_PROVIDER="AWS"
    HOME_DIR="/home/ec2-user"
    PACKAGE_MANAGER="yum"
    PYTHON_PACKAGE="python3"
elif curl -s -f -m 1 http://metadata.google.internal > /dev/null 2>&1; then
    CLOUD_PROVIDER="GCP"
    HOME_DIR="/home/ubuntu"
    PACKAGE_MANAGER="apt-get"
    PYTHON_PACKAGE="python3"
elif curl -s -f -m 1 -H Metadata:true "http://169.254.169.254/metadata/instance?api-version=2021-02-01" > /dev/null 2>&1; then
    CLOUD_PROVIDER="Azure"
    HOME_DIR="/home/azureuser"
    PACKAGE_MANAGER="apt-get"
    PYTHON_PACKAGE="python3"
else
    echo "Unknown cloud provider"
    exit 1
fi

echo "Detected cloud provider: $CLOUD_PROVIDER"
echo "Home directory: $HOME_DIR"

# --- System Setup ---
echo "Updating system and installing dependencies..."

if [ "$PACKAGE_MANAGER" = "yum" ]; then
    sudo yum update -y
    sudo yum install -y git $PYTHON_PACKAGE ${PYTHON_PACKAGE}-pip gcc gcc-c++ gcc-gfortran make cmake
    # Install development tools for building scientific packages
    sudo yum groupinstall -y "Development Tools"
    sudo yum install -y openblas-devel lapack-devel
elif [ "$PACKAGE_MANAGER" = "apt-get" ]; then
    sudo apt-get update
    sudo apt-get install -y git $PYTHON_PACKAGE ${PYTHON_PACKAGE}-pip build-essential gfortran cmake
    # Install BLAS/LAPACK for scientific computing
    sudo apt-get install -y libopenblas-dev liblapack-dev
fi

# Install Python packages
echo "Installing Python packages..."
sudo ${PYTHON_PACKAGE} -m pip install --upgrade pip
sudo ${PYTHON_PACKAGE} -m pip install pyscf numpy scipy h5py

# Install rclone
echo "Installing rclone..."
curl https://rclone.org/install.sh | sudo bash

# --- Configure Rclone ---
echo "Configuring rclone..."
mkdir -p $HOME_DIR/.config/rclone

# Retrieve rclone configuration based on cloud provider
if [ "$CLOUD_PROVIDER" = "AWS" ]; then
    # Get region from instance metadata
    REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
    # Use AWS CLI to fetch the secret
    aws secretsmanager get-secret-value \
        --secret-id $RCLONE_CONFIG_SECRET_NAME \
        --region $REGION \
        --query SecretString \
        --output text > $HOME_DIR/.config/rclone/rclone.conf
elif [ "$CLOUD_PROVIDER" = "GCP" ]; then
    # Use gcloud to access secret manager
    gcloud secrets versions access latest \
        --secret=$RCLONE_CONFIG_SECRET_NAME \
        > $HOME_DIR/.config/rclone/rclone.conf
elif [ "$CLOUD_PROVIDER" = "Azure" ]; then
    # Use Azure CLI to fetch from Key Vault
    # Assumes the instance has managed identity with access to the key vault
    VAULT_NAME="${KEY_VAULT_NAME:-cloud-scheduler-vault}"
    az keyvault secret show \
        --vault-name $VAULT_NAME \
        --name $RCLONE_CONFIG_SECRET_NAME \
        --query value -o tsv > $HOME_DIR/.config/rclone/rclone.conf
fi

# Set proper permissions
sudo chown -R $(basename $HOME_DIR):$(basename $HOME_DIR) $HOME_DIR/.config

# --- Get and Build Code ---
echo "Setting up computation code..."
cd $HOME_DIR

# Clone the SHCI repository if provided
if [ "$SHCI_REPO_URL" != "https://github.com/your_username/your_shci_repo.git" ]; then
    echo "Cloning SHCI repository..."
    git clone $SHCI_REPO_URL shci_code
    cd shci_code
    
    # Build if Makefile exists
    if [ -f Makefile ]; then
        echo "Building SHCI code..."
        make -j$(nproc)
    fi
    cd $HOME_DIR
fi

# Copy run_calculation.py if it exists in the bootstrap directory
if [ -f /var/lib/cloud/instance/scripts/run_calculation.py ]; then
    cp /var/lib/cloud/instance/scripts/run_calculation.py $HOME_DIR/
elif [ -f /tmp/run_calculation.py ]; then
    cp /tmp/run_calculation.py $HOME_DIR/
fi

# --- Prepare Output Directory ---
OUTPUT_DIR="$HOME_DIR/shci_output"
mkdir -p $OUTPUT_DIR
sudo chown -R $(basename $HOME_DIR):$(basename $HOME_DIR) $OUTPUT_DIR

# --- Create sync script ---
cat > $HOME_DIR/sync_results.sh << 'EOF'
#!/bin/bash
OUTPUT_DIR="$1"
GDRIVE_REMOTE="$2"
GDRIVE_DEST_DIR="$3"

echo "[$(date)] Syncing results to ${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}..."
rclone sync "$OUTPUT_DIR" "${GDRIVE_REMOTE}:${GDRIVE_DEST_DIR}" \
    --create-empty-src-dirs \
    --progress \
    --log-file="$OUTPUT_DIR/rclone.log" \
    --log-level INFO

if [ $? -eq 0 ]; then
    echo "[$(date)] Sync completed successfully"
else
    echo "[$(date)] Sync failed with error code $?"
fi
EOF

chmod +x $HOME_DIR/sync_results.sh

# --- Run Calculation ---
echo "Starting calculation..."

# Check if run_calculation.py exists
if [ -f $HOME_DIR/run_calculation.py ]; then
    # Run the calculation
    cd $HOME_DIR
    sudo -u $(basename $HOME_DIR) ${PYTHON_PACKAGE} run_calculation.py \
        --basis "aug-cc-pVDZ" \
        --output_dir $OUTPUT_DIR \
        > $OUTPUT_DIR/calculation.log 2>&1 &
    CALC_PID=$!
    
    echo "Calculation started with PID $CALC_PID"
    
    # Create a monitoring script
    cat > $HOME_DIR/monitor_calculation.sh << EOF
#!/bin/bash
CALC_PID=$CALC_PID
OUTPUT_DIR="$OUTPUT_DIR"
GDRIVE_REMOTE="$GDRIVE_REMOTE"
GDRIVE_DEST_DIR="$GDRIVE_DEST_DIR"

# Initial sync after 1 minute
sleep 60
$HOME_DIR/sync_results.sh "\$OUTPUT_DIR" "\$GDRIVE_REMOTE" "\$GDRIVE_DEST_DIR"

# Sync every 5 minutes while calculation runs
while kill -0 \$CALC_PID 2>/dev/null; do
    sleep 300
    $HOME_DIR/sync_results.sh "\$OUTPUT_DIR" "\$GDRIVE_REMOTE" "\$GDRIVE_DEST_DIR"
done

# Final sync
echo "Calculation completed. Performing final sync..."
$HOME_DIR/sync_results.sh "\$OUTPUT_DIR" "\$GDRIVE_REMOTE" "\$GDRIVE_DEST_DIR"

# Create completion marker
echo "Calculation completed at $(date)" > \$OUTPUT_DIR/COMPLETED

# Final sync with completion marker
$HOME_DIR/sync_results.sh "\$OUTPUT_DIR" "\$GDRIVE_REMOTE" "\$GDRIVE_DEST_DIR"

# Shutdown instance
echo "Shutting down instance in 30 seconds..."
sleep 30
sudo shutdown -h now
EOF
    
    chmod +x $HOME_DIR/monitor_calculation.sh
    
    # Run the monitoring script in the background
    nohup sudo -u $(basename $HOME_DIR) $HOME_DIR/monitor_calculation.sh > $OUTPUT_DIR/monitor.log 2>&1 &
    
else
    echo "Warning: run_calculation.py not found!"
    echo "Creating a demo calculation..."
    
    # Create a demo calculation that runs for a few minutes
    cat > $OUTPUT_DIR/demo_calculation.txt << EOF
This is a demo calculation.
Started at: $(date)
Instance type: $(curl -s http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null || echo "Unknown")
Cloud provider: $CLOUD_PROVIDER

Since run_calculation.py was not found, this instance will run for 5 minutes
and then shut down. In a real scenario, you would:

1. Include run_calculation.py in your repository
2. Or copy it to the instance during launch
3. Or include it in a custom AMI/image

The instance will sync this demo output to Google Drive and then terminate.
EOF
    
    # Run for 5 minutes then shutdown
    (
        for i in {1..5}; do
            echo "[$(date)] Demo minute $i/5" >> $OUTPUT_DIR/demo_calculation.txt
            $HOME_DIR/sync_results.sh "$OUTPUT_DIR" "$GDRIVE_REMOTE" "$GDRIVE_DEST_DIR"
            sleep 60
        done
        
        echo "[$(date)] Demo completed" >> $OUTPUT_DIR/demo_calculation.txt
        $HOME_DIR/sync_results.sh "$OUTPUT_DIR" "$GDRIVE_REMOTE" "$GDRIVE_DEST_DIR"
        
        echo "Demo completed. Shutting down..."
        sudo shutdown -h now
    ) > $OUTPUT_DIR/demo_monitor.log 2>&1 &
fi

echo "Bootstrap script completed. Calculation and monitoring processes running in background."