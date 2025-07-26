#!/bin/bash
# Build and push Docker image to container registry
set -e

# Configuration
IMAGE_NAME="${IMAGE_NAME:-quantum-chemistry}"
TAG="${TAG:-latest}"
REGISTRY="${REGISTRY:-ghcr.io/cloud-scheduler}"
FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME:$TAG"

echo "Building Docker image: $FULL_IMAGE_NAME"

# Build the image
docker build -t "$FULL_IMAGE_NAME" .

# Also tag as latest
docker tag "$FULL_IMAGE_NAME" "$REGISTRY/$IMAGE_NAME:latest"

echo "Docker image built successfully"

# Test the image locally
echo "Testing Docker image..."
docker run --rm -e "JOB_ID=test" -e "BASIS_SET=sto-3g" "$FULL_IMAGE_NAME" python3 -c "import pyscf; print('PySCF version:', pyscf.__version__)"

if [ "$1" = "--push" ]; then
    echo "Pushing image to registry..."
    
    # Login to registry (assumes you're already authenticated)
    # For GitHub Container Registry: docker login ghcr.io -u username -p token
    # For Docker Hub: docker login -u username -p password
    
    docker push "$FULL_IMAGE_NAME"
    docker push "$REGISTRY/$IMAGE_NAME:latest"
    
    echo "Image pushed successfully to $REGISTRY"
    echo "Use the following in your deployments:"
    echo "  DOCKER_IMAGE=$FULL_IMAGE_NAME"
else
    echo "Image built locally. To push to registry, run:"
    echo "  $0 --push"
fi

echo "Build completed successfully"