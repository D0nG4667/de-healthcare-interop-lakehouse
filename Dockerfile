# ==============================================================================
# Multi-Stage Enterprise Dockerfile — Healthcare Clinical Interoperability Lakehouse
# ==============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv from official Astral container image
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /uvx /bin/

# Copy dependency specifications first for deterministic layer caching
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY tests/ ./tests/
COPY scripts/ ./scripts/

RUN uv sync --frozen --dev

# Default entrypoint executes the Medallion pipeline with HIPAA Safe Harbor audit
ENTRYPOINT ["uv", "run", "--no-sync", "healthcare-lakehouse"]
CMD ["run-pipeline", "--patients", "12", "--seed", "42", "--output-dir", "/app/data/container_run", "--verify-hipaa"]
