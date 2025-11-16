# hydra-jobs

A distributed job runner with a FastAPI scheduler, cross‑platform workers, Redis for coordination, and MongoDB for job definitions and run history. Comes with Docker Compose for a one‑command local stack.

## Overview

- Scheduler service (Python/FastAPI) exposes a REST API to submit jobs, query job and run metadata, list workers, and exposes a health endpoint. The scheduler also dispatches jobs from the pending queue to eligible workers and performs failover.
- Worker service (Python) registers to Redis, heartbeats, consumes its queue, executes jobs with configurable concurrency, and persists run results to MongoDB.
- Redis coordinates: job queues, worker heartbeats, and in‑flight job markers.
- MongoDB stores: job definitions, job runs (history), and can be queried by API.

## Architecture Diagram

```
        +----------------+             +-----------------+
        |    FastAPI     |  REST API   |   submit_job    |
        |   Scheduler    | <---------  |   (curl/py)     |
        +-------+--------+             +-----------------+
                |                               ^
                |                               |
        dispatch|                               |
                v                               |
        +----------------+      heartbeats       |
        |     Redis      | <---------------------+
        |  queues+state  | -----------------> worker queues
        +--------+-------+                      ^
                 |                              |
                 v                              | execute + report
        +----------------+                      |
        |    Workers     |----------------------+
        |  (Linux/Win)   |   MongoDB (runs/defs)
        +----------------+           |
                                     v
                               +-----------+
                               |  MongoDB  |
                               +-----------+
```

## How Scheduler Works

- BLPOP `job_queue:pending` and fetch the job definition from MongoDB.
- Discover online workers via `worker_heartbeats` TTL; filter by:
  - `max_concurrency > current_running`
  - OS, tags, and allowed_users affinity
- Select best worker by lowest load and RPUSH the job ID to `job_queue:<worker_id>`.
- Insert a pending `job_runs` document (worker updates it on start/finish).
- Periodically scan for stale heartbeats; for offline workers requeue their running jobs.

## How Workers Work

- Register in `workers:<worker_id>` with OS, tags, allowed users, and `max_concurrency`.
- Send heartbeats every 2 seconds to `worker_heartbeats`.
- BLPOP from `job_queue:<worker_id>`; for each job:
  - Atomically `HINCRBY` current_running and track `worker_running_set:<worker_id>`.
  - Start a run entry (status=running); execute the command with OS‑appropriate shell.
  - Update Mongo with stdout, stderr, return code, and status; decrement counters and clear Redis markers.

## Redis Usage

- `workers:<worker_id>`: hash with worker metadata, `max_concurrency`, `current_running`, status
- `worker_heartbeats`: sorted set `id -> timestamp`
- `job_queue:pending`: list of job IDs awaiting assignment
- `job_queue:<worker_id>`: per‑worker list of job IDs
- `job_running:<job_id>`: hash with `worker_id`, `heartbeat`, `user`
- `worker_running_set:<worker_id>`: set of active job IDs

## MongoDB Usage

Collections:
- `job_definitions` — job documents with `_id` (string), name, user, affinity, shell, command, retries, timeout, schedule, timestamps
- `job_runs` — run history with job_id, user, worker_id, timestamps, status, returncode, stdout, stderr

## Quick Start

- Prereqs: Docker + Docker Compose

```
docker-compose up --build
```

Once running:

```
python examples/submit_job.py
# or
bash examples/submit_job.sh
```

Check status:

```
curl http://localhost:8000/health
curl http://localhost:8000/workers/
```

## Write Your Own Worker

- Set env vars: `WORKER_ID`, `WORKER_TAGS` (comma‑sep), `ALLOWED_USERS` (comma‑sep), `MAX_CONCURRENCY`.
- Ensure it registers in `workers:<id>`, heartbeats to `worker_heartbeats`, and processes `job_queue:<id>`.
- Respect atomic counters (`current_running`) and `worker_running_set:<id>` membership.

## Submit Jobs

POST `http://localhost:8000/jobs/` with JSON body:

```
{
  "name": "test-echo",
  "user": "rich",
  "affinity": { "os": ["linux"], "tags": [], "allowed_users": ["rich"] },
  "command": "echo 'hello world'",
  "shell": "bash",
  "retries": 0,
  "timeout": 10
}
```

Then query:

- `GET /jobs/{job_id}` — job metadata
- `GET /jobs/{job_id}/runs` — run history
- `GET /workers/` — workers
- `GET /health` — scheduler health

## Debugging Tips

- Redis keys: inspect with `redis-cli` (`keys workers:*`, `zrange worker_heartbeats 0 -1 withscores`).
- Mongo collections: `job_definitions`, `job_runs`.
- Logs: adjust `LOG_LEVEL` env to `DEBUG`.
- If no eligible worker, the scheduler requeues and retries — check worker OS/tags/users.

## Roadmap

- Pluggable executors (containers, SSH).
- Backoff with dead‑letter queues.
- Job scheduling / cron support.
- Authentication and multi‑tenant namespaces.
- UI for monitoring and job submission.

