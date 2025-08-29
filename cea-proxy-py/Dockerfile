# syntax=docker/dockerfile:1.7

# -------- Base image with Python runtime --------
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Avoids "setuptools not found" with some wheels
    SETUPTOOLS_USE_DISTUTILS=stdlib

# Install system dependencies required by common Python packages and for runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# -------- Dependencies layer --------
# Copy only requirements first to leverage Docker layer caching
COPY src/requirements.txt ./requirements.txt

# Create a dedicated virtual environment inside the image for isolation
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

# Ensure the venv is on PATH
ENV PATH="/opt/venv/bin:$PATH"

# -------- Application code layer --------
# Copy the application source code
COPY src/ ./src/
COPY m365agents*.yml ./
COPY appPackage/ ./appPackage/

# Expose the port configured in DefaultConfig (3978)
EXPOSE 3978

# Default environment variables (override in runtime as needed)
ENV HOST=0.0.0.0 \
    PORT=3978

# Run the app
CMD ["python", "src/app.py"]
