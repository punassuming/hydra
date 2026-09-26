# Hydra Go Worker

A Go implementation of the Hydra worker with feature parity to the existing
Python worker (`worker/`).

## Status

**Feature-complete.** The Go worker supports all core functionality of the
Python worker including job execution, heartbeats, concurrency control, log
streaming, kill support, source fetching, and retry logic.

### Supported Features

| Feature | Status |
|---------|--------|
| Shell executor | ✅ |
| External executor | ✅ |
| Batch executor | ✅ |
| Python executor | ✅ |
| PowerShell executor | ✅ |
| Heartbeat + metrics | ✅ |
| Concurrency control | ✅ |
| Bypass concurrency | ✅ |
| Run lifecycle events (run_start/run_end) | ✅ |
| Log streaming (Redis pub/sub + history) | ✅ |
| Kill listener (job cancellation) | ✅ |
| Completion criteria (exit codes, stdout/stderr patterns) | ✅ |
| Retry logic | ✅ |
| Source fetching (git, copy, rsync) | ✅ |
| Git sparse checkout | ✅ |
| Git PAT authentication | ✅ |
| Environment injection (params) | ✅ |
| Timeout support | ✅ |
| Worker ops logging | ✅ |
| Rich registration (OS, capabilities, shells, hostname) | ✅ |
| Domain-scoped Redis ACL | ✅ |
| SQL executor | ✅ (bridges through a bundled Python interpreter — no native Go DB drivers) |
| Impersonation / Kerberos | ✅ (Linux/macOS, via `sudo`/`kinit`) |

## Prerequisites

- Go 1.26 or later
- A running Redis instance (default: `redis://localhost:6379/0`)
- A valid Hydra scheduler with a provisioned domain token

## Configuration

The worker is configured entirely through environment variables (same as the
Python worker). You can also place a `.env` file in the working directory and it
will be loaded automatically at startup.

| Variable | Default | Description |
|----------|---------|-------------|
| `API_TOKEN` | *(required)* | Domain token issued by the scheduler |
| `DOMAIN` | `prod` | Domain this worker belongs to |
| `WORKER_ID` | `worker-<hostname>-<pid>` | Unique worker identifier |
| `WORKER_TAGS` | *(none)* | Comma-separated affinity tags |
| `ALLOWED_USERS` | *(none)* | Comma-separated allowed users |
| `MAX_CONCURRENCY` | `2` | Maximum concurrent jobs |
| `WORKER_STATE` | `online` | Initial state (`online`/`draining`/`offline`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_PASSWORD` | *(none)* | Redis ACL password (domain-scoped) |
| `DEPLOYMENT_TYPE` | `docker` | Deployment type metadata |
| `WORKER_METRICS_SAMPLE_SECONDS` | `15` | Metrics sampling interval |
| `WORKER_METRICS_WINDOW_SECONDS` | `1800` | Metrics history retention window |

## Building

```bash
# Native binary for the current platform
go build -o hydra-go-worker ./...

# Cross-compile for Linux (e.g. for Docker images)
GOOS=linux GOARCH=amd64 go build -o hydra-go-worker-linux ./...

# Cross-compile for Windows
GOOS=windows GOARCH=amd64 go build -o hydra-go-worker.exe ./...

# Cross-compile for macOS (Apple Silicon)
GOOS=darwin GOARCH=arm64 go build -o hydra-go-worker-darwin ./...
```

## Running

```bash
API_TOKEN=<domain_token> DOMAIN=prod \
  REDIS_URL=redis://localhost:6379/0 \
  ./hydra-go-worker
```

## Testing

```bash
cd go-worker
go test ./...
```

## Project Structure

```
go-worker/
├── main.go                         # Entry point
├── go.mod / go.sum                 # Go module
├── README.md                       # This file
└── internal/
    ├── config/
    │   ├── config.go               # Environment-variable configuration
    │   └── config_test.go          # Config tests
    ├── redisclient/
    │   └── client.go               # Redis connection setup (go-redis)
    ├── executor/
    │   ├── executor.go             # Job execution engine (shell/external/batch/python/powershell)
    │   └── executor_test.go        # Executor tests
    ├── source/
    │   └── source.go               # Source provisioning (git/copy/rsync)
    └── worker/
        ├── worker.go               # Worker registration, heartbeat, poll loop, job lifecycle
        ├── metrics.go              # Process/memory metrics collection
        └── worker_test.go          # Worker tests
```
