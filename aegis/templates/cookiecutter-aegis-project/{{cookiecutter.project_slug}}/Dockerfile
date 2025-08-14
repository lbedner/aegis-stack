FROM python:3.11-slim

# Install system dependencies and clean up
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
    && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install uv with specific version for reproducibility
RUN pip install --no-cache-dir uv==0.4.18

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/code \
    UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /code

# Copy dependency files and README (needed by pyproject.toml)
COPY pyproject.toml uv.lock README.md /code/

# Install dependencies
RUN uv sync --all-extras && \
    rm -rf /tmp/uv-cache

# Copy application code
COPY . /code

# Make entrypoint executable
RUN chmod +x /code/scripts/entrypoint.sh

# Set default port as an environment variable
ARG PORT=8000
ENV PORT=$PORT

# Expose the port
EXPOSE $PORT

# Add health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:$PORT/health || exit 1


# Labels for better container management
LABEL maintainer="contact@aegis-stack.dev" \
      version="0.1.0" \
      description="Aegis Stack - Production-ready async Python foundation"

ENTRYPOINT ["uv", "run", "/code/scripts/entrypoint.sh"]