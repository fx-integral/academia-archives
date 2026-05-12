# Basic Dockerfile for the calculator environment base image
FROM python:3.13-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Install dependencies (uncomment and add if env.py requires packages)
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# Copy the environment script
COPY env.py .

# Default command (overridden by affinetes in the wrapper image)
CMD ["python", "env.py"]