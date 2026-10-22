"""Post-run policy shared by the full and lite editions.

Pure functions: given a run's terminal status and its job definition, decide what happens next.
The persistence and queueing around the decision differ per edition; the decision must not.
"""

import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from .retry import apply_retry_jitter, compute_retry_backoff_delay

TRIGGER_DEPENDENTS = "trigger_dependents"
RETRY = "retry"
FINAL_FAILURE = "final_failure"
NONE = "none"


@dataclass(frozen=True)
class PostRunDecision:
    action: str
    retry_attempt: int = 0  # the attempt number the retry run will carry (RETRY only)
    delay_seconds: int = 0  # jittered backoff before the retry may start (RETRY only)


def decide_post_run(
    status: str,
    job: Optional[Mapping[str, Any]],
    retry_attempt: int = 0,
    rng: Callable[[], float] = random.random,
) -> PostRunDecision:
    """What to do after a run reaches terminal ``status``.

    success                -> trigger dependents
    failed/timed_out       -> retry while ``retry_attempt < max_retries``, else final failure
                              (failure webhooks/alerts); an unknown job gets no action
    anything else          -> nothing
    """
    if status == "success":
        return PostRunDecision(TRIGGER_DEPENDENTS)
    if status not in {"failed", "timed_out"} or not job:
        return PostRunDecision(NONE)
    max_retries = int(job.get("max_retries", 0) or 0)
    if max_retries > 0 and retry_attempt < max_retries:
        next_attempt = retry_attempt + 1
        delay = apply_retry_jitter(compute_retry_backoff_delay(int(job.get("retry_delay_seconds", 0) or 0), next_attempt), rng)
        return PostRunDecision(RETRY, retry_attempt=next_attempt, delay_seconds=delay)
    return PostRunDecision(FINAL_FAILURE)


def sla_exceeded(job: Optional[Mapping[str, Any]], elapsed_seconds: float) -> bool:
    """Whether a still-running run has outlived its job's ``sla_max_duration_seconds``."""
    try:
        sla = int((job or {}).get("sla_max_duration_seconds") or 0)
    except (TypeError, ValueError):
        return False
    return sla > 0 and elapsed_seconds > sla
