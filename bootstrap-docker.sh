#!/bin/bash
# Simplified bootstrap script for Docker-based deployments
set -e
set -x

# --- Configuration ---
DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/cloud-scheduler/quantum-chemistry:latest}"
JOB_ID="${JOB_ID:-unknown}"
S3_BUCKET="${S3_BUCKET:-}"
S3_INPUT_PATH="${S3_INPUT_PATH:-}"
GDRIVE_PATH="${GDRIVE_PATH:-shci_jobs/results_$(date +%Y-%m-%d_%H-%M-%S)}"
BASIS_SET="${BASIS_SET:-aug-cc-pVDZ}"
SHCI_EXECUTABLE="${SHCI_EXECUTABLE:-./shci_program}"

# Detect cloud provider and set home directory
if [ -f /sys/hypervisor/uuid ] && grep -q ^ec2 /sys/hypervisor/uuid; then
    CLOUD_PROVIDER="AWS"
    HOME_DIR="/home/ec2-user"
    PACKAGE_MANAGER="yum"
elif curl -s -f -m 1 http://metadata.google.internal > /dev/null 2>&1; then
    CLOUD_PROVIDER="GCP"
    HOME_DIR="/home/ubuntu"
    PACKAGE_MANAGER="apt-get"
elif curl -s -f -m 1 -H Metadata:true "http://169.254.169.254/metadata/instance?api-version=2021-02-01" > /dev/null 2>&1; then
    CLOUD_PROVIDER="Azure"
    HOME_DIR="/home/azureuser"
    PACKAGE_MANAGER="apt-get"
else
    echo "Unknown cloud provider, defaulting to generic setup"
    CLOUD_PROVIDER="Generic"
    HOME_DIR="/home/ubuntu"
    PACKAGE_MANAGER="apt-get"
fi

echo "Detected cloud provider: $CLOUD_PROVIDER"
echo "Home directory: $HOME_DIR"
echo "Using Docker image: $DOCKER_IMAGE"

# --- Install Docker ---
echo "Installing Docker..."

if [ "$PACKAGE_MANAGER" = "yum" ]; then
    # Amazon Linux / RHEL
    sudo yum update -y
    sudo yum install -y docker
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -a -G docker $(basename $HOME_DIR)
elif [ "$PACKAGE_MANAGER" = "apt-get" ]; then
    # Ubuntu / Debian
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release
    
    # Add Docker's official GPG key
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    
    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Add user to docker group
    sudo usermod -a -G docker $(basename $HOME_DIR)
fi

# Wait for Docker to be ready
echo "Waiting for Docker to be ready..."
sleep 5

# Test Docker installation
if sudo docker --version; then
    echo "Docker installed successfully"
else
    echo "Docker installation failed"
    exit 1
fi

# --- Pull Docker Image ---
echo "Pulling Docker image: $DOCKER_IMAGE"
if ! sudo docker pull "$DOCKER_IMAGE"; then
    echo "Failed to pull Docker image. Attempting to build locally..."
    
    # If pull fails, try to build from source (if available)
    if [ -f "$HOME_DIR/Dockerfile" ]; then
        cd "$HOME_DIR"
        sudo docker build -t quantum-chemistry:local .
        DOCKER_IMAGE="quantum-chemistry:local"
    else
        echo "Error: Cannot pull or build Docker image"
        exit 1
    fi
fi

# --- Setup Output Directory ---
OUTPUT_DIR="$HOME_DIR/output"
sudo mkdir -p "$OUTPUT_DIR"
sudo chown -R $(basename $HOME_DIR):$(basename $HOME_DIR) "$OUTPUT_DIR"

# --- Create monitoring script ---
cat > "$HOME_DIR/monitor_container.sh" << 'EOF'
#!/bin/bash
CONTAINER_NAME="$1"
OUTPUT_DIR="$2"
GDRIVE_PATH="$3"

echo "Monitoring container: $CONTAINER_NAME"

# Wait for container to start
sleep 30

# Monitor container status and sync results periodically
while sudo docker ps | grep -q "$CONTAINER_NAME"; do
    echo "[$(date)] Container $CONTAINER_NAME is running"
    
    # Check if output directory has new files and sync them
    if [ -d "$OUTPUT_DIR" ] && [ "$(ls -A $OUTPUT_DIR 2>/dev/null)" ]; then
        echo "[$(date)] Syncing intermediate results..."
        
        # Use rclone from the container to sync results
        sudo docker exec "$CONTAINER_NAME" /app/scripts/sync_to_gdrive.sh /app/output "$GDRIVE_PATH" || true
    fi
    
    sleep 300  # Check every 5 minutes
done

echo "[$(date)] Container $CONTAINER_NAME has stopped"

# Final sync after container completion
if [ -d "$OUTPUT_DIR" ] && [ "$(ls -A $OUTPUT_DIR 2>/dev/null)" ]; then
    echo "[$(date)] Performing final sync..."
    # Try to sync from stopped container
    if sudo docker ps -a | grep -q "$CONTAINER_NAME"; then
        sudo docker start "$CONTAINER_NAME" 2>/dev/null || true
        sudo docker exec "$CONTAINER_NAME" /app/scripts/sync_to_gdrive.sh /app/output "$GDRIVE_PATH" || true
        sudo docker stop "$CONTAINER_NAME" 2>/dev/null || true
    fi
fi

echo "[$(date)] Monitoring completed"
EOF

chmod +x "$HOME_DIR/monitor_container.sh"

# --- Run Docker Container ---
echo "Starting quantum chemistry calculation in Docker container..."

CONTAINER_NAME="quantum-calc-$JOB_ID"

# Run container with environment variables
sudo docker run \
    --name "$CONTAINER_NAME" \
    --rm \
    -v "$OUTPUT_DIR:/app/output" \
    -e "JOB_ID=$JOB_ID" \
    -e "S3_BUCKET=$S3_BUCKET" \
    -e "S3_INPUT_PATH=$S3_INPUT_PATH" \
    -e "GDRIVE_PATH=$GDRIVE_PATH" \
    -e "BASIS_SET=$BASIS_SET" \
    -e "SHCI_EXECUTABLE=$SHCI_EXECUTABLE" \
    -e "AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION" \
    -e "RCLONE_SECRET_NAME=$RCLONE_SECRET_NAME" \
    -e "KEY_VAULT_NAME=$KEY_VAULT_NAME" \
    "$DOCKER_IMAGE" &

DOCKER_PID=$!

echo "Container started with PID $DOCKER_PID"

# Start monitoring in background
"$HOME_DIR/monitor_container.sh" "$CONTAINER_NAME" "$OUTPUT_DIR" "$GDRIVE_PATH" > "$OUTPUT_DIR/monitor.log" 2>&1 &

MONITOR_PID=$!

echo "Monitoring started with PID $MONITOR_PID"

# Wait for container to complete
wait $DOCKER_PID
CONTAINER_EXIT_CODE=$?

echo "Container completed with exit code: $CONTAINER_EXIT_CODE"

# Copy results from container to host
if sudo docker ps -a | grep -q "$CONTAINER_NAME"; then
    echo "Copying final results from container..."
    sudo docker cp "$CONTAINER_NAME:/app/output/." "$OUTPUT_DIR/" 2>/dev/null || true
fi

# Stop monitoring
kill $MONITOR_PID 2>/dev/null || true

# Create completion marker
echo "Bootstrap completed at: $(date)" > "$OUTPUT_DIR/BOOTSTRAP_COMPLETED"
echo "Container exit code: $CONTAINER_EXIT_CODE" >> "$OUTPUT_DIR/BOOTSTRAP_COMPLETED"

echo "Bootstrap script completed successfully"

# Shutdown instance
echo "Shutting down instance in 60 seconds..."
sleep 60
sudo shutdown -h now