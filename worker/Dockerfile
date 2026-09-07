FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Compose runs the worker as this dedicated non-root identity. Override at
# build time (--build-arg) if these need to change; docker-compose.yml's
# HYDRA_WORKER_UID/GID (see .env.example) pass the same values through so
# the build and the compose `user:` field stay in sync from one source.
ARG HYDRA_WORKER_UID=10001
ARG HYDRA_WORKER_GID=10001
RUN groupadd --gid "${HYDRA_WORKER_GID}" hydra \
    && useradd --uid "${HYDRA_WORKER_UID}" --gid "${HYDRA_WORKER_GID}" --no-create-home --shell /usr/sbin/nologin hydra

RUN pip install --no-cache-dir uv==0.5.13
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY worker /app/worker

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Liveness check: the heartbeat loop touches WORKER_HEARTBEAT_FILE every
# ~2s regardless of Redis reachability, so a stale/missing file means the
# worker's main thread is hung or crashed (not just disconnected from Redis).
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,time; p=os.getenv('WORKER_HEARTBEAT_FILE','/tmp/hydra_worker_heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p)<30 else 1)"

CMD ["python", "-m", "worker.worker"]
