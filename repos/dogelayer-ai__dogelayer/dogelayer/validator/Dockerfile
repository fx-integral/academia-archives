# DogeLayer Validator Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    iputils-ping \
    net-tools \
    && rm -rf /var/lib/apt/lists/*


# Copy project files
COPY pyproject.toml ./
COPY dogelayer ./dogelayer

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Force install specific version of bittensor (this will invoke Rust compiler)
RUN pip install --no-cache-dir --force-reinstall \
    bittensor==9.10.1 \
    bittensor-wallet==4.0.1 \
    tabulate \
    python-dotenv

# Create necessary directories
RUN mkdir -p /app/config \
    && mkdir -p /root/.bittensor/wallets \
    && mkdir -p /root/.bittensor/chains \
    && mkdir -p /root/.bittensor/neurons

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import dogelayer.validator.validator; print('Validator import successful')" || exit 1

# Startup command - supports command line arguments
ENTRYPOINT ["python", "-m", "dogelayer.validator.validator"]
CMD ["run"]
