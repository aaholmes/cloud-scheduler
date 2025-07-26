#!/bin/bash
# Download input files from S3
set -e

S3_PATH="$1"
LOCAL_DIR="$2"

if [ -z "$S3_PATH" ] || [ -z "$LOCAL_DIR" ]; then
    echo "Usage: $0 <s3_path> <local_dir>"
    exit 1
fi

echo "Downloading files from $S3_PATH to $LOCAL_DIR"

# Create local directory
mkdir -p "$LOCAL_DIR"

# Extract bucket and prefix from S3 path
if [[ $S3_PATH =~ ^s3://([^/]+)/(.*)$ ]]; then
    BUCKET="${BASH_REMATCH[1]}"
    PREFIX="${BASH_REMATCH[2]}"
else
    echo "Error: Invalid S3 path format: $S3_PATH"
    exit 1
fi

echo "Bucket: $BUCKET"
echo "Prefix: $PREFIX"

# Download files using AWS CLI
aws s3 sync "s3://$BUCKET/$PREFIX" "$LOCAL_DIR" \
    --exclude "*.log" \
    --exclude "*.tmp"

# List downloaded files
echo "Downloaded files:"
find "$LOCAL_DIR" -type f -exec ls -lh {} \;

# Make any executable files executable
find "$LOCAL_DIR" -name "shci*" -exec chmod +x {} \;
find "$LOCAL_DIR" -name "*.sh" -exec chmod +x {} \;

echo "S3 download completed successfully"