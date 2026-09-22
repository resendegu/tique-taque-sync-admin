# ==============================================================================
# TiqueTaque Sync Admin — Enterprise Multi-Arch Dockerfile (ARM64 & AMD64)
# ==============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Defaults de container. HOST/PORT são lidos pelo CMD lá embaixo, então mudar a
# porta pelo ConfigMap realmente muda a porta em que a aplicação escuta.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/data

WORKDIR /app

# Install runtime dependencies and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/
COPY pyproject.toml .

# Create volume mount point for persistent SQLite data
RUN mkdir -p /app/data && chown -R 1000:1000 /app

USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/healthz" || exit 1

# Forma shell para expandir HOST/PORT; o `exec` mantém o uvicorn como PID 1, de
# modo que ele receba o SIGTERM do Kubernetes e encerre com graça.
CMD ["sh", "-c", "exec uvicorn src.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
