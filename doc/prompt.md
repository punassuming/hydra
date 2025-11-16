You are to generate a complete, production-ready repository that implements the following system:

---

## **System Summary**

Create a distributed job runner with:

1. **Scheduler service** (Python/FastAPI)
2. **Worker service** (Python) with multi-concurrency execution
3. **Redis** for coordination (queues, heartbeats)
4. **MongoDB** for job definitions, run history, worker metadata
5. **REST API** to submit jobs, query status, and register/update job definitions
6. **Affinity logic** (OS, tags, and allowed_users)
7. **Worker concurrency limits** (each worker processes up to a configured N tasks in parallel)
8. **Failover:** if a worker dies mid-job, the scheduler detects it and requeues the job
9. **Cross-platform worker architecture:** worker must run on Linux or Windows
10. **Docker Compose stack** to run scheduler + workers + Redis + Mongo locally
11. **Full quick-start docs**, examples, and test scripts

Name the project: **"hydra-jobs"**
Language: **Python 3.11+**

---

## **Repository Structure**

Generate this complete directory structure:

```
hydra-jobs/
├── docker-compose.yml
├── README.md
├── scheduler/
│   ├── main.py
│   ├── scheduler.py
│   ├── redis_client.py
│   ├── mongo_client.py
│   ├── models/
│   │   ├── job_definition.py
│   │   ├── job_run.py
│   │   ├── worker_info.py
│   ├── utils/
│   │   ├── affinity.py
│   │   ├── failover.py
│   │   ├── selectors.py
│   │   ├── logging.py
│   ├── api/
│   │   ├── jobs.py
│   │   ├── workers.py
│   │   ├── health.py
│   └── requirements.txt
├── worker/
│   ├── worker.py
│   ├── executor.py
│   ├── redis_client.py
│   ├── mongo_client.py
│   ├── config.py
│   ├── utils/
│   │   ├── os_exec.py
│   │   ├── heartbeat.py
│   │   ├── concurrency.py
│   └── requirements.txt
├── examples/
│   ├── submit_job.sh
│   ├── submit_job.py
│   ├── example_jobs.json
└── tests/
    ├── test_scheduler.py
    ├── test_worker.py
    ├── test_end_to_end.py
```

---

## **Functional Requirements**

### **1. Job Model (MongoDB)**

`job_definition` fields:

```
{
  _id: string,             // job_id
  name: string,
  user: string,
  affinity: {
    os: [string],          // e.g. ["linux", "windows"]
    tags: [string],        // e.g. ["gpu", "backup"]
    allowed_users: [string]
  },
  shell: string,           // "bash" | "powershell" | "cmd"
  command: string,
  retries: int,
  timeout: int,
  schedule: string | null,
  created_at: datetime,
  updated_at: datetime
}
```

### **2. Job Runs (MongoDB)**

```
{
  _id: auto,
  job_id: string,
  user: string,
  worker_id: string,
  start_ts: datetime,
  end_ts: datetime | null,
  status: "pending" | "running" | "success" | "failed",
  returncode: int | null,
  stdout: string,
  stderr: string
}
```

### **3. Redis Keys**

```
workers:<worker_id>         // hash: metadata, allowed_users, tags, max_concurrency, current_running
worker_heartbeats           // sorted set: id -> timestamp
job_queue:pending           // list: unassigned jobs
job_queue:<worker_id>       // list: each worker’s queue
job_running:<job_id>        // hash: worker_id, started_ts, heartbeat, user
worker_running_set:<worker_id> // set: active job_ids
```

Workers must:

• decrement/increment current_running atomically
• add/remove job_ids from worker_running_set

---

## **4. Scheduler Behavior**

The scheduler:

1. Continuously BLPOP from `job_queue:pending`
2. Reads job definition from Mongo
3. Filters workers by:
   • online status
   • `max_concurrency > current_running`
   • matching OS
   • matching tags
   • allowed_users includes the job user
4. Selects best worker (lowest load)
5. Pushes job to `job_queue:<worker_id>`
6. Inserts initial job_run record into Mongo
7. Periodically checks hearts:
   • any worker whose heartbeat is too old → mark offline
   • any job it was running → requeue

Implement all of this.

---

## **5. Worker Behavior**

Each worker:

1. Registers itself in Redis on startup
2. Sends heartbeats every 2 seconds
3. Has a configurable `max_concurrency`
4. Spawns a thread pool to execute jobs concurrently
5. Each job is executed using OS-appropriate executor:
   • Linux → `/bin/bash`
   • Windows → `powershell.exe` or `cmd.exe`
6. Writes `stdout`, `stderr`, `returncode` into Mongo
7. Updates Redis `current_running` and `worker_running_set`

Workers must work on Windows and Linux by inspecting `platform.system()`.

---

## **6. REST API (FastAPI)**

### Endpoints

```
POST /jobs/                 → submit job definition or immediate job run
GET  /jobs/{job_id}         → fetch metadata
GET  /jobs/{job_id}/runs    → fetch run history
GET  /workers/              → list workers
GET  /health                → scheduler health check
```

---

## **7. Docker Compose Requirements**

Create a working docker compose environment containing:

```
services:
  scheduler: python service
  worker1: python service
  worker2: python service
  redis: latest
  mongo: latest
```

Workers should auto-register and begin processing jobs.

---

## **8. Example Scripts**

Under `examples/` include:

### `submit_job.py`

Sends a job to the API:

```python
{
  "name": "test-echo",
  "user": "rich",
  "affinity": { "os": ["linux"], "tags": [], "allowed_users": ["rich"] },
  "command": "echo 'hello world'",
  "shell": "bash"
}
```

### `submit_job.sh`

Shell wrapper:

```
curl -X POST http://localhost:8000/jobs -H "Content-Type: application/json" -d @example_jobs.json
```

---

## **9. README Requirements**

README.md must include:

### _Sections:_

1. Overview
2. Architecture diagram
3. How scheduler works
4. How workers work
5. How Redis is used
6. How Mongo is used
7. Quick start

   ```
   docker-compose up --build
   python examples/submit_job.py
   ```

8. How to write your own worker
9. How to submit jobs
10. Debugging tips
11. Roadmap

Clear instructions, no missing steps.

---

# **Final Instructions**

Generate:

• Full code
• Full docs
• All Dockerfiles
• All Python modules
• A fully runnable local system
• Deep comments explaining logic

Produce the entire repository scaffold and implementation.

Do not skip sections.
Do not summarize.
Generate real code.

---
