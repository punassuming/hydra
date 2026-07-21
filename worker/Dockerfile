FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY . /app/worker
WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Liveness check: the heartbeat loop touches WORKER_HEARTBEAT_FILE every
# ~2s regardless of Redis reachability, so a stale/missing file means the
# worker's main thread is hung or crashed (not just disconnected from Redis).
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,time; p=os.getenv('WORKER_HEARTBEAT_FILE','/tmp/hydra_worker_heartbeat'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p)<30 else 1)"

CMD ["python", "-m", "worker.worker"]
