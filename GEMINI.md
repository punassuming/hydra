# Hydra Jobs

## Project Overview

Hydra Jobs is a distributed job runner designed for flexibility and scalability. It features a FastAPI-based scheduler, cross-platform python workers, and a React-based user interface.

**Key Components:**

*   **Scheduler Service:** A Python FastAPI application that exposes a REST API for job management. It handles job submission, validation, scheduling (cron/interval), and dispatching to workers via Redis. It also supports Server-Sent Events (SSE) for real-time updates.
    *   **AI Integration:** Uses Google Gemini or OpenAI for generating job definitions from natural language and analyzing job failures.
*   **Worker Service:** A Python application that consumes jobs from Redis queues. It supports various execution environments (shell, python, batch) and handles concurrency, heartbeats, and result reporting to MongoDB.
    *   **Git Support:** Can clone and execute code directly from Git repositories.
*   **UI:** A React application built with Vite, TypeScript, and Ant Design. It provides a visual interface for monitoring jobs, workers, and run history, with integrated AI tools.
*   **Data Store:**
    *   **Redis:** Used for job queues, worker coordination, heartbeats, and pub/sub.
    *   **MongoDB:** Stores persistent data including job definitions, run history, and domain metadata.

## Architecture

*   **Language:** Python 3.11 (Backend), TypeScript (Frontend)
*   **Frameworks:** FastAPI (Scheduler), React + Vite (UI)
*   **Database:** MongoDB (v6.0 recommended, v5.0 for broader CPU support), Redis (v7-alpine)
*   **AI Provider:** Google Gemini (requires `GEMINI_API_KEY`) or OpenAI (requires `OPENAI_API_KEY`)
*   **Infrastructure:** Docker & Docker Compose

## Building and Running

The project relies heavily on Docker Compose for orchestration.

### Prerequisites

*   Docker
*   Docker Compose
*   Git (for local development)

### Quick Start (Full Stack)

To start the scheduler, worker, UI, Redis, and MongoDB:

```bash
# Using the helper script (recommended for dev)
./scripts/dev-up.sh

# OR using docker-compose directly
ADMIN_TOKEN=admin_secret GEMINI_API_KEY=<your_key> OPENAI_API_KEY=<your_key> docker compose up --build
```

The services will be available at:
*   **UI:** http://localhost:5173
*   **Scheduler API:** http://localhost:8000
*   **Redis:** localhost:6379
*   **MongoDB:** localhost:27017

### Running a Worker Separately

Workers can be run independently to scale processing power.

```bash
API_TOKEN=<domain_token> WORKER_DOMAIN=prod \
REDIS_URL=redis://localhost:6379/0 MONGO_URL=mongodb://localhost:27017 \
docker compose -f docker-compose.worker.yml up --build
```

### Helper Scripts

Located in `scripts/`:
*   `dev-up.sh`: Starts the development stack.
*   `dev-down.sh`: Stops the development stack.
*   `test.sh`: Runs Python backend tests.
*   `test-all.sh`: Runs all tests.
*   `worker-up.sh`: Helper to start a worker.

## Development Conventions

### Backend (Python)

*   **Location:** `scheduler/` and `worker/`
*   **Style:** Adheres to standard Python 3.11 practices. Type hints are encouraged.
*   **Testing:** Uses `pytest`.
    *   Run tests: `./scripts/test.sh` or `pytest tests/`
    *   Test files located in `tests/`

### Frontend (React)

*   **Location:** `ui/`
*   **Stack:** React, TypeScript, Vite, Ant Design.
*   **Testing:** Uses `vitest`.
    *   Run tests: `cd ui && npm test`
*   **Linting:** Standard Vite/React configurations.

### AI Features

*   **Magic Job Generator:** In the UI "New Job" form, use natural language to generate job JSON. Select between Gemini and OpenAI from the dropdown.
*   **Failure Analysis:** In the Run Logs view, click "Analyze Failure" to get AI-driven remediation steps. Select between Gemini and OpenAI.
*   **Configuration:** Ensure `GEMINI_API_KEY` and/or `OPENAI_API_KEY` are set in the Scheduler environment.

### Git Source Execution

Jobs can now specify a git repository as a source.

```json
{
  "source": {
    "url": "https://github.com/user/repo.git",
    "ref": "main",
    "path": "scripts"
  },
  "executor": { "type": "shell", "script": "./run.sh" }
}
```

The worker will clone the repo to a temporary directory, switch to `path` (if provided), and execute the script within that context.

### Workflow

1.  **Database State:** MongoDB uses a named volume `mongo-data` for persistence.
2.  **Environment Variables:** Controlled via `.env` file (see `.env.example`).
3.  **Logs:** Configurable via `LOG_LEVEL` environment variable.

## Key Files & Directories

*   `scheduler/main.py`: Entry point for the FastAPI scheduler.
*   `scheduler/api/ai.py`: AI endpoints (Generate/Analyze).
*   `worker/worker.py`: Entry point for the Worker process.
*   `worker/utils/git.py`: Git clone/checkout logic.
*   `ui/src/App.tsx`: Main React component.
*   `docker-compose.yml`: Core service definition.
*   `tests/`: Backend integration and unit tests.
*   `examples/`: Scripts for submitting sample jobs (`submit_job.py`, `seed_test_jobs.py`).
