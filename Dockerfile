# Multi-stage Docker build for quantum chemistry calculations
FROM ubuntu:22.04 as builder

# Avoid interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    gfortran \
    git \
    wget \
    curl \
    python3 \
    python3-pip \
    python3-dev \
    libopenblas-dev \
    liblapack-dev \
    libhdf5-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /opt/quantum

# Install Python packages
COPY requirements-docker.txt .
RUN pip3 install --no-cache-dir -r requirements-docker.txt

# Download and install rclone
RUN curl https://rclone.org/install.sh | bash

# Create final runtime image
FROM ubuntu:22.04

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libopenblas0 \
    liblapack3 \
    libhdf5-103 \
    curl \
    awscli \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages and binaries from builder
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin/rclone /usr/local/bin/rclone

# Create application directory
WORKDIR /app

# Create user for running calculations (security best practice)
RUN useradd -m -u 1000 quantum && \
    chown -R quantum:quantum /app

# Copy application files
COPY run_calculation.py /app/
COPY container_scripts/ /app/scripts/

# Make scripts executable
RUN chmod +x /app/scripts/*.sh

# Switch to non-root user
USER quantum

# Set Python path
ENV PYTHONPATH=/usr/local/lib/python3.10/dist-packages:$PYTHONPATH

# Default command
CMD ["/app/scripts/run_container.sh"]