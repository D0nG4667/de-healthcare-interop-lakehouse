# syntax=docker/dockerfile:1
# ==============================================================================
# Enterprise Multi-Stage Dockerfile — Healthcare Clinical Interoperability Lakehouse
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: builder — Deterministic dependency & wheel builder with BuildKit cache
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Phase 1: Install third-party locked dependencies prior to copying source code
# so source edits never invalidate the dependency layer cache.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Phase 2: Copy project metadata and clinical lakehouse source and install package
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ------------------------------------------------------------------------------
# Stage 2: qa — Immutable CI/CD Quality Assurance, Type-Safety & 100% Coverage
# ------------------------------------------------------------------------------
FROM builder AS qa

ARG UID=10001
ARG GID=10001

COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY lefthook.yml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --dev \
    && groupadd --system --gid "${GID}" lakehouse \
    && useradd --system --gid "${GID}" --uid "${UID}" --create-home lakehouse \
    && chown -R lakehouse:lakehouse /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER lakehouse
WORKDIR /app

ENTRYPOINT ["pytest"]
CMD ["--cov=src/healthcare_lakehouse", "--cov-branch", "--cov-report=term-missing", "--cov-fail-under=100"]

# ------------------------------------------------------------------------------
# Stage 3: runtime — Hardened Non-Root Production Runtime (Zero uv / Zero Dev Tools)
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="de-healthcare-interop-lakehouse" \
      org.opencontainers.image.description="HL7 v2 / FHIR R4 Clinical Interoperability Medallion Lakehouse with HIPAA Safe Harbor De-Identification" \
      org.opencontainers.image.vendor="Enterprise Data Engineering" \
      org.opencontainers.image.licenses="MIT"

ARG UID=10001
ARG GID=10001

# Create unprivileged system user and writable data mount directory
RUN groupadd --system --gid "${GID}" lakehouse \
    && useradd --system --gid "${GID}" --uid "${UID}" --home-dir /nonexistent --shell /usr/sbin/nologin --no-create-home lakehouse \
    && mkdir -p /app/data \
    && chown -R lakehouse:lakehouse /app

# Copy only the compiled virtual environment and package from builder (no uv binary)
COPY --from=builder --chown=lakehouse:lakehouse /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER lakehouse

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["healthcare-lakehouse", "--help"]

ENTRYPOINT ["healthcare-lakehouse"]
CMD ["run-pipeline", "--patients", "12", "--seed", "42", "--output-dir", "/app/data/container_run", "--verify-hipaa"]
