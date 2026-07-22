"""Standalone control-plane entrypoint for Hydra.

Run this process separately from the API service to achieve process-level
separation between API serving and background orchestration.

    python -m scheduler.orchestrator_entrypoint

The process:
1. Performs the same domain/token initialisation as the API on startup.
2. Starts all standard orchestration loops via ``OrchestratorManager``.
3. Writes a heartbeat to Redis (``hydra:orchestrator:heartbeat``) so the
   ``GET /health/orchestration`` API endpoint can report whether the
   control-plane is running and making progress.
4. Blocks until SIGTERM / SIGINT, then cleanly stops all loops.

Environment variables are identical to the scheduler API service
(``REDIS_URL``, ``MONGO_URL``, ``ADMIN_TOKEN``, etc.).  Set
``HYDRA_MODE=api`` on the scheduler API service so it does not also start
the orchestration loops.
"""

import signal
import sys

from .orchestrator import create_standard_orchestrator
from .startup import ensure_admin_token, ensure_domains_seeded, warn_credential_encryption_key
from .utils.logging import setup_logging

log = setup_logging("scheduler.orchestrator_entrypoint")


def main() -> None:
    log.info("Hydra control-plane orchestrator starting")

    # Perform the same initialization steps as the API startup.
    ensure_admin_token()
    warn_credential_encryption_key()
    ensure_domains_seeded()

    mgr = create_standard_orchestrator()
    mgr.start()

    log.info(
        "Control-plane orchestrator running. Loops: %s",
        mgr.loop_names,
    )

    # Handle graceful shutdown on SIGTERM (Kubernetes / Docker) and SIGINT (Ctrl-C).
    def _shutdown(signum: int, _frame) -> None:
        log.info("Received signal %d — shutting down orchestrator", signum)
        mgr.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Block the main thread.  The manager's daemon threads keep the loops alive;
    # the main thread just waits for the stop event (set by a signal handler or
    # if all loops exit on their own).
    mgr.stop_event.wait()
    log.info("Orchestrator stop_event set — exiting")


if __name__ == "__main__":
    main()
