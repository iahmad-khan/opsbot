FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency installation
RUN pip install uv

WORKDIR /app

# ---- dependencies layer ----
FROM base AS deps
COPY pyproject.toml .
RUN uv pip install --system -e ".[dev]"

# ---- production image ----
FROM base AS production
COPY --from=deps /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=deps /usr/local/bin /usr/local/bin
COPY . .

# Node.js for MCP servers
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uvicorn", "opsbot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- worker image ----
FROM production AS worker
CMD ["celery", "-A", "opsbot.tasks.celery_app:celery_app", "worker", \
     "--loglevel=info", "--concurrency=4", "-Q", "default,approvals,sre"]

# ---- beat scheduler image ----
FROM production AS beat
CMD ["celery", "-A", "opsbot.tasks.celery_app:celery_app", "beat", \
     "--loglevel=info", "--scheduler=redbeat.RedBeatScheduler"]
