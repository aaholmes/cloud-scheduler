# Docker Containerization Guide

The cloud scheduler supports Docker containerization for robust, reproducible quantum chemistry environments. This eliminates dependency issues and ensures consistent execution across different cloud providers and instance types.

## Benefits of Docker Approach

✅ **Reproducible Environment**: Exact same software versions every time  
✅ **Eliminated Dependency Conflicts**: All packages pre-installed and tested  
✅ **Faster Instance Startup**: No compilation or package installation on instances  
✅ **OS Independence**: Works on any Linux distribution  
✅ **Version Control**: Docker images are versioned and immutable  
✅ **Easy Updates**: Simply build and push new container images  

## Quick Start with Docker

### 1. Build the Docker Image

```bash
# Build locally
docker build -t quantum-chemistry .

# Or use the build script
./build_and_push_docker.sh
```

### 2. Run Jobs with Docker

```bash
# Use Docker deployment
python cloud_run.py my_calculation \
    --s3-bucket my-bucket \
    --from-spot-prices \
    --docker

# Specify custom Docker image
python cloud_run.py my_calculation \
    --s3-bucket my-bucket \
    --from-spot-prices \
    --docker \
    --docker-image my-registry/quantum-chemistry:v2.0
```

## Docker Image Structure

### Base Environment
- **OS**: Ubuntu 22.04 LTS
- **Python**: 3.10
- **Scientific Libraries**: PySCF, NumPy, SciPy
- **Cloud Tools**: AWS CLI, rclone
- **Build Tools**: Pre-compiled for performance

### Container Contents
```
/app/
├── run_calculation.py          # Main calculation script
├── scripts/
│   ├── run_container.sh        # Container entrypoint
│   ├── download_s3_files.sh    # S3 file download
│   ├── setup_rclone.sh         # Google Drive setup
│   └── sync_to_gdrive.sh       # Result synchronization
├── input/                      # Job input files (mounted)
└── output/                     # Calculation results (mounted)
```

## Container Workflow

### 1. Container Startup
```bash
docker run \
    -v ./output:/app/output \
    -e JOB_ID=abc123 \
    -e S3_INPUT_PATH=s3://bucket/job/input/ \
    -e GDRIVE_PATH=results/water_dimer \
    -e BASIS_SET=aug-cc-pVTZ \
    quantum-chemistry:latest
```

### 2. Automatic Process
1. **Download**: Fetch input files from S3
2. **Setup**: Configure rclone for Google Drive access
3. **Calculate**: Run quantum chemistry calculation
4. **Sync**: Upload results to Google Drive (excluding FCIDUMP)
5. **Complete**: Container exits with status code

### 3. Host Monitoring
The `bootstrap-docker.sh` script on the host:
- Monitors container status
- Performs periodic result syncing
- Handles container lifecycle
- Manages instance shutdown

## Building Custom Images

### 1. Customize the Dockerfile

```dockerfile
# Add custom quantum chemistry software
FROM ubuntu:22.04
# ... base setup ...

# Install custom software
COPY my_shci_program /opt/quantum/bin/
RUN chmod +x /opt/quantum/bin/my_shci_program

# Add to PATH
ENV PATH="/opt/quantum/bin:$PATH"
```

### 2. Build and Test

```bash
# Build custom image
docker build -t my-quantum-chemistry:v1.0 .

# Test locally
docker run --rm -e JOB_ID=test my-quantum-chemistry:v1.0 python3 -c "import pyscf; print('OK')"
```

### 3. Push to Registry

```bash
# Tag for registry
docker tag my-quantum-chemistry:v1.0 ghcr.io/myorg/quantum-chemistry:v1.0

# Push to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u myusername --password-stdin
docker push ghcr.io/myorg/quantum-chemistry:v1.0
```

## Local Development and Testing

### Using Docker Compose

```bash
# Set environment variables
export JOB_ID=local-test
export BASIS_SET=sto-3g
export GDRIVE_PATH=test/results

# Run with docker-compose
docker-compose up
```

### Manual Container Testing

```bash
# Create test directories
mkdir -p input output

# Copy test files
cp my_shci_program input/
cp input.inp input/

# Run container
docker run --rm \
    -v ./input:/app/input:ro \
    -v ./output:/app/output \
    -e JOB_ID=test \
    -e BASIS_SET=sto-3g \
    quantum-chemistry:latest
```

## Container Environment Variables

### Required Variables
- **`JOB_ID`**: Unique job identifier
- **`S3_INPUT_PATH`**: S3 path to input files
- **`GDRIVE_PATH`**: Google Drive destination path
- **`BASIS_SET`**: Quantum chemistry basis set

### Optional Variables
- **`SHCI_EXECUTABLE`**: Path to SHCI program (default: `./shci_program`)
- **`DOCKER_IMAGE`**: Override default container image
- **`RCLONE_SECRET_NAME`**: Secret manager key name for rclone config
- **`KEY_VAULT_NAME`**: Azure Key Vault name (for Azure deployments)

### Cloud Provider Variables
- **`AWS_DEFAULT_REGION`**: AWS region for S3 and Secrets Manager
- **`GOOGLE_APPLICATION_CREDENTIALS`**: GCP service account key path

## Registry Configuration

### GitHub Container Registry (Recommended)

```bash
# Login to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u username --password-stdin

# Build and push
./build_and_push_docker.sh --push
```

### Docker Hub

```bash
# Login to Docker Hub
docker login -u username -p password

# Tag and push
docker tag quantum-chemistry:latest username/quantum-chemistry:latest
docker push username/quantum-chemistry:latest
```

### Private Registry

```json
{
  "docker": {
    "enabled": true,
    "image": "my-registry.com/quantum-chemistry:latest",
    "registry_username": "myuser",
    "registry_password": "mypassword"
  }
}
```

## Integration with Cloud Providers

### AWS ECS/Fargate
For serverless container execution:

```bash
# Create ECS task definition
aws ecs register-task-definition --cli-input-json file://task-definition.json

# Run task
aws ecs run-task --cluster my-cluster --task-definition quantum-chemistry
```

### Google Cloud Run
For managed container execution:

```bash
# Deploy to Cloud Run
gcloud run deploy quantum-chemistry \
    --image ghcr.io/myorg/quantum-chemistry:latest \
    --platform managed \
    --memory 8Gi \
    --cpu 4
```

### Azure Container Instances
For simple container execution:

```bash
# Create container group
az container create \
    --resource-group my-rg \
    --name quantum-calc \
    --image ghcr.io/myorg/quantum-chemistry:latest \
    --cpu 4 \
    --memory 8
```

## Troubleshooting

### Container Build Issues

```bash
# Check build logs
docker build --no-cache -t quantum-chemistry . 2>&1 | tee build.log

# Test specific layers
docker run --rm -it ubuntu:22.04 bash
```

### Runtime Issues

```bash
# Check container logs
docker logs quantum-calc

# Debug interactively
docker run --rm -it --entrypoint bash quantum-chemistry:latest

# Check resource usage
docker stats quantum-calc
```

### Registry Issues

```bash
# Test registry connectivity
docker pull ghcr.io/myorg/quantum-chemistry:latest

# Check authentication
docker login ghcr.io

# Verify image metadata
docker inspect ghcr.io/myorg/quantum-chemistry:latest
```

## Performance Considerations

### Image Size Optimization
- Use multi-stage builds to reduce final image size
- Remove build dependencies in final stage
- Use `.dockerignore` to exclude unnecessary files

### Runtime Performance
- Pre-compile Python modules in container
- Use optimized BLAS/LAPACK libraries
- Consider GPU-enabled base images for supported calculations

### Resource Limits
```bash
# Set memory and CPU limits
docker run --memory=8g --cpus=4 quantum-chemistry:latest
```

## Security Best Practices

### Container Security
- Run as non-root user (already implemented)
- Use minimal base images
- Regularly update base images for security patches
- Scan images for vulnerabilities

### Secrets Management
- Never embed secrets in images
- Use cloud provider secret managers
- Mount secrets as volumes when needed

### Network Security
- Use private registries for sensitive images
- Implement image signing and verification
- Restrict container network access when possible

## Migration from Traditional Bootstrap

### Advantages of Docker Approach
1. **Reliability**: No more failed package installations
2. **Speed**: Faster instance startup (no compilation)
3. **Consistency**: Identical environment every time
4. **Maintenance**: Easier to update and test environments

### Migration Steps
1. **Build Docker image** with your quantum chemistry stack
2. **Test locally** with docker-compose
3. **Push to registry** (GitHub Container Registry recommended)
4. **Update cloud_run.py** to use `--docker` flag
5. **Deploy and test** on cloud instances

### Backward Compatibility
Both approaches are supported:
- **Traditional**: Uses `bootstrap.sh` for package installation
- **Docker**: Uses `bootstrap-docker.sh` for container execution

Choose based on your needs:
- Docker for production/reproducible environments
- Traditional for development/custom setups