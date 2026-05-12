# SN92 Validator Docker Image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    iputils-ping \
    net-tools netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install bittensor python-dotenv pyyaml httpx bittensor-cli
RUN pip install --no-cache-dir torch==2.3.0+cpu -f https://download.pytorch.org/whl/cpu/torch_stable.html

# Create necessary directories
RUN mkdir -p /root/.bittensor/wallets \
    && mkdir -p /root/.bittensor/chains \
    && mkdir -p /root/.bittensor/neurons

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD nc -z localhost 19292 || exit 1

# Copy project files
COPY . /app
COPY Docker/validator/start-validator.sh /start-validator.sh
RUN chmod +x /start-validator.sh

# Startup command - supports command line arguments
ENTRYPOINT ["/start-validator.sh"]