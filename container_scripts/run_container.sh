#!/bin/bash
# Main container entrypoint script
set -e

echo "=== Quantum Chemistry Container Starting ==="
echo "Container started at: $(date)"
echo "Working directory: $(pwd)"
echo "User: $(whoami)"
echo "Python version: $(python3 --version)"

# Check environment variables
echo "=== Environment Variables ==="
echo "JOB_ID: ${JOB_ID:-not set}"
echo "S3_BUCKET: ${S3_BUCKET:-not set}"
echo "S3_INPUT_PATH: ${S3_INPUT_PATH:-not set}"
echo "GDRIVE_PATH: ${GDRIVE_PATH:-not set}"
echo "BASIS_SET: ${BASIS_SET:-aug-cc-pVDZ}"
echo "SHCI_EXECUTABLE: ${SHCI_EXECUTABLE:-./shci_program}"

# Create output directory
OUTPUT_DIR="/app/output"
mkdir -p "$OUTPUT_DIR"
echo "Output directory: $OUTPUT_DIR"

# Download input files from S3
if [ -n "$S3_INPUT_PATH" ]; then
    echo "=== Downloading Input Files from S3 ==="
    /app/scripts/download_s3_files.sh "$S3_INPUT_PATH" /app/input
else
    echo "Warning: No S3_INPUT_PATH specified, using local files only"
fi

# Setup rclone configuration
echo "=== Setting up Google Drive Access ==="
/app/scripts/setup_rclone.sh

# Run the quantum chemistry calculation
echo "=== Starting Calculation ==="
cd /app
python3 run_calculation.py \
    --basis "${BASIS_SET}" \
    --output_dir "$OUTPUT_DIR" \
    --shci-executable "${SHCI_EXECUTABLE}" \
    2>&1 | tee "$OUTPUT_DIR/container.log"

CALC_EXIT_CODE=$?

echo "=== Calculation completed with exit code: $CALC_EXIT_CODE ==="

# Sync results to Google Drive
if [ -n "$GDRIVE_PATH" ]; then
    echo "=== Syncing Results to Google Drive ==="
    /app/scripts/sync_to_gdrive.sh "$OUTPUT_DIR" "$GDRIVE_PATH"
else
    echo "Warning: No GDRIVE_PATH specified, skipping Google Drive sync"
fi

# Create completion marker
echo "Container completed at: $(date)" > "$OUTPUT_DIR/CONTAINER_COMPLETED"
echo "Exit code: $CALC_EXIT_CODE" >> "$OUTPUT_DIR/CONTAINER_COMPLETED"

echo "=== Container Execution Complete ==="
exit $CALC_EXIT_CODE