#!/bin/bash
# Sync results to Google Drive
set -e

OUTPUT_DIR="$1"
GDRIVE_PATH="$2"

if [ -z "$OUTPUT_DIR" ] || [ -z "$GDRIVE_PATH" ]; then
    echo "Usage: $0 <output_dir> <gdrive_path>"
    exit 1
fi

echo "Syncing $OUTPUT_DIR to gdrive:$GDRIVE_PATH"

# Check if rclone is configured
if ! rclone listremotes | grep -q "gdrive"; then
    echo "Error: Google Drive remote 'gdrive' not configured"
    echo "Available remotes:"
    rclone listremotes
    exit 1
fi

# Test connectivity
echo "Testing Google Drive connectivity..."
if ! rclone lsd gdrive: >/dev/null 2>&1; then
    echo "Warning: Cannot access Google Drive. Sync may fail."
    echo "Attempting sync anyway..."
fi

# Perform sync with exclusions
echo "Starting rclone sync..."
rclone sync "$OUTPUT_DIR" "gdrive:$GDRIVE_PATH" \
    --create-empty-src-dirs \
    --exclude "FCIDUMP" \
    --exclude "*.tmp" \
    --exclude "*.lock" \
    --progress \
    --log-level INFO \
    --log-file="$OUTPUT_DIR/rclone_sync.log" \
    --stats 30s

SYNC_EXIT_CODE=$?

if [ $SYNC_EXIT_CODE -eq 0 ]; then
    echo "Sync to Google Drive completed successfully"
    echo "Results available at: gdrive:$GDRIVE_PATH"
    
    # Log sync completion
    echo "Sync completed at: $(date)" >> "$OUTPUT_DIR/sync_history.log"
    echo "Destination: gdrive:$GDRIVE_PATH" >> "$OUTPUT_DIR/sync_history.log"
    
else
    echo "Sync to Google Drive failed with exit code: $SYNC_EXIT_CODE"
    echo "Check $OUTPUT_DIR/rclone_sync.log for details"
fi

exit $SYNC_EXIT_CODE