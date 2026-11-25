# Local development image: dev dependencies included, source code bind-mounted at /app.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UV_LINK_MODE=copy \
    # Keep the venv outside /app so the source bind mount does not hide it.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        gettext \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Optional corporate CA certificates: any ssl_certifactes/*.crt in the build context is trusted.
# Missing certificates do not fail the build (developers outside the corporate network).
RUN --mount=type=bind,source=.,target=/ctx \
    (cp /ctx/ssl_certifactes/*.crt /usr/local/share/ca-certificates/ 2>/dev/null || true) \
    && update-ca-certificates

RUN python -m pip install --upgrade pip uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages
# All dependency groups (dev included) for tests, debugging and auto-reload.
RUN uv sync --frozen --no-install-project

COPY ./compose/production/django/entrypoint /entrypoint
COPY ./compose/local/django/start /start
COPY ./compose/local/django/celery/worker/start /start-celeryworker
COPY ./compose/local/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /entrypoint /start /start-celeryworker /start-celerybeat \
    && chmod +x /entrypoint /start /start-celeryworker /start-celerybeat

ENTRYPOINT ["/entrypoint"]
