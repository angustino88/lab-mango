# ============================================================
# Stage 1: OS base with Python 3.12 + uv
# ============================================================
FROM python:3.12-slim-bookworm AS python-base

ARG PIP_INDEX_URL=""
ARG PIP_EXTRA_INDEX_URL=""

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip uv

# ============================================================
# Stage 2: Build — install production Python dependencies
# ============================================================
FROM python-base AS build-stage

WORKDIR /app

ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
# drf-api-contracts is a local editable path dependency (pyproject [tool.uv.sources]);
# uv needs its sources to resolve the lockfile.
COPY packages ./packages
# Install only production deps (no dev group)
RUN uv sync --frozen --no-dev --no-install-project

# ============================================================
# Stage 3: Run — lean production image
# ============================================================
FROM python-base AS run-stage

ARG APP_HOME=/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=${APP_HOME}

WORKDIR ${APP_HOME}

# Non-root django user for production
RUN addgroup --system django \
    && adduser --system --ingroup django django

# Runtime system dependencies
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        gettext \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Bosch CA certificates
COPY ./ssl_certifactes/RB_IssuingCA_RSA_G21.crt \
    /usr/local/share/ca-certificates/RB_IssuingCA_RSA_G21.crt

COPY ./ssl_certifactes/RB_RootCA_RSA_G01.crt \
    /usr/local/share/ca-certificates/RB_RootCA_RSA_G01.crt

RUN update-ca-certificates

# Copy venv from build stage
COPY --from=build-stage /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY --chown=django:django ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint && chmod +x /entrypoint

COPY --chown=django:django ./compose/production/django/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

COPY --chown=django:django ./compose/production/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker && chmod +x /start-celeryworker

COPY --chown=django:django ./compose/production/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat && chmod +x /start-celerybeat

COPY --chown=django:django . ${APP_HOME}

USER django

ENTRYPOINT ["/entrypoint"]
