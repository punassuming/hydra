# Documentation

Hydra's documentation is organized by topic so the `docs/` directory stays easy to scan.

## Core docs

- [`architecture.md`](architecture.md) — system architecture with Mermaid diagrams:
  - Component overview and runtime modes (combined vs separated)
  - System architecture flowchart
  - Job dispatch sequence diagram
  - Worker deployment options
  - Multi-domain security model
  - Failover sequence diagram
  - Job run state machine
  - Redis key layout and security boundaries
  - Executor types and workspace caching
  - Run lifecycle and event ingestion semantics
  - Backpressure and queue visibility

## Deployment

- [`windows-worker-bootstrap.md`](windows-worker-bootstrap.md) — running a Hydra worker on Windows as either a Task Scheduler watchdog or a Windows Service (NSSM)
- [`../deploy/helm/hydra/README.md`](../deploy/helm/hydra/README.md) — Kubernetes deployment via the Helm chart (multi-domain worker pools, home-lab image loading, ingress)

## Development

- [`development/docker-compose-workflows.md`](development/docker-compose-workflows.md) — local Docker and Compose workflows
- [`development/testing.md`](development/testing.md) — testing guardrails and test runner guidance

## Design notes

- [`design/executor-improvements.md`](design/executor-improvements.md) — executor design backlog and implementation plan

## Reference

- [`reference/generation-prompt.md`](reference/generation-prompt.md) — original repository generation prompt kept for reference

## UI

- [`ui/theming.md`](ui/theming.md) — UI theming conventions and usage
- [`ui/operator-journey.md`](ui/operator-journey.md) — sign-in, job execution,
  logs, worker operations, and the browser-coverage boundary

## Archive

- [`archive/job-management-improvements.md`](archive/job-management-improvements.md) — consolidated historical notes for the job-management improvements work
