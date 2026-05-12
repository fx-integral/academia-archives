FROM python:3.12-slim AS builder

WORKDIR /build

# Install system deps for bittensor (rust/cargo for substrate)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

# hatchling's wheel builder needs the package source tree present at
# `pip install` time, so we copy the full tree first. The install must
# be non-editable: the runtime stage relocates the source from /build
# to /app, and an editable .pth pointing at /build would
# ModuleNotFoundError post-copy.
COPY . .
RUN pip install --no-cache-dir .

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages and app from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build /app

RUN useradd -m -r appuser && \
    mkdir -p /app/data /home/appuser/.bittensor && \
    chown -R appuser:appuser /app /home/appuser/.bittensor
USER appuser

EXPOSE 8422

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8422/health/ready || exit 1

CMD ["djinn-miner"]
