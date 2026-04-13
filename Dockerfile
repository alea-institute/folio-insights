# syntax=docker/dockerfile:1.7

# =========================================================================
# Stage 1: Build the SvelteKit viewer
# =========================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/viewer

# Copy package manifests first for better layer caching
COPY viewer/package.json viewer/package-lock.json ./

RUN npm ci --no-audit --no-fund

# Copy the rest of the viewer source and build
COPY viewer/ ./

RUN npm run build

# =========================================================================
# Stage 2: Python runtime with FastAPI + built viewer + bundled data
# =========================================================================
FROM python:3.11-slim

# Bring in uv for fast, deterministic Python installs (matches folio-mapper)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps: build-essential for any C extensions (sentence-transformers etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cacheable layer)
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the project + its runtime deps. fastapi + uvicorn come in via
# the project deps chain (sse-starlette -> starlette -> (fastapi via pyproject)).
# If the runtime fails with "fastapi not found", add fastapi + uvicorn[standard]
# explicitly to pyproject.toml dependencies and rebuild.
RUN uv pip install --system --no-cache . \
    && uv pip install --system --no-cache fastapi "uvicorn[standard]" python-multipart

# Copy backend application code
COPY api/ ./api/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/viewer/build/ ./viewer/build/

# Bundle the extraction output dataset (3.8 MB per CONTEXT.md)
COPY output/ ./output/

# Create non-root user with writable home dir for any runtime job state
RUN useradd -m -r appuser \
    && mkdir -p /home/appuser/.folio-insights \
    && chown -R appuser:appuser /app /home/appuser
USER appuser

# Standard env
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FOLIO_INSIGHTS_OUTPUT_DIR=/app/output

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')"

# Railway injects PORT; fall back to 8000 for local `docker run`
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
