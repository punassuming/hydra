from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Run lifecycle state constants
# ---------------------------------------------------------------------------
# States progress in this general order:
#   pending → dispatched → running → success | failed | timed_out
#
# Retries and failover:
#   A failed/timed_out run may be re-enqueued by the scheduler (max_retries)
#   or requeued by the failover loop (worker offline).  Each re-enqueue
#   creates a *new* run document with a fresh run_id so prior history is
#   preserved.  The original run document is left in its terminal state.
#
# State meanings:
#   pending     – job has been enqueued in the pending queue but not yet
#                 dispatched to a worker.
#   dispatched  – scheduler has pushed the job envelope to a worker queue;
#                 the worker has not yet acknowledged execution start.
#   running     – worker has emitted run_start; execution is in progress.
#   success     – worker emitted run_end with status "success".
#   failed      – worker emitted run_end with status "failed", or the
#                 scheduler/failover loop marked the run terminal.
#   timed_out   – run exceeded its configured timeout; treated as terminal.
#
# TERMINAL_STATES: any state from which a run document must not transition
# further.  Post-run actions (retries, webhooks, emails) fire exactly once
# when a run first enters a terminal state.

RunStatus = Literal["pending", "dispatched", "running", "success", "failed", "timed_out"]

TERMINAL_STATES: frozenset[str] = frozenset({"success", "failed", "timed_out"})


class JobRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(default=None, alias="_id")
    job_id: str
    user: str
    domain: str = "prod"
    worker_id: Optional[str] = None
    start_ts: Optional[datetime] = None
    scheduled_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    status: str = "pending"  # pending | dispatched | running | success | failed | timed_out
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    slot: Optional[int] = None
    attempt: Optional[int] = None
    retries_remaining: Optional[int] = None
    schedule_tick: Optional[str] = None
    schedule_mode: Optional[str] = None
    executor_type: Optional[str] = None
    queue_latency_ms: Optional[float] = None
    completion_reason: Optional[str] = None
    duration: Optional[float] = None
    bypass_concurrency: Optional[bool] = None
    sla_miss_alerted: bool = False
