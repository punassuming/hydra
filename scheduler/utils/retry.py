"""Retry backoff shared by the full and lite editions (scheduler-level job retries)."""

import os
import random

# Ceiling for the exponential retry backoff, mirroring the 2s-doubling shape used for
# connection-retry backoff elsewhere (worker/worker.py's kill-listener reconnect loop uses
# 2s -> 60s; job retries default to a longer cap since they represent actual work being redone).
RETRY_BACKOFF_CAP_SECONDS = int(os.getenv("SCHEDULER_RETRY_BACKOFF_CAP_SECONDS", "300"))
# +/- fraction of the backoff delay randomised per retry, so a burst of jobs that failed together
# (e.g. a downstream outage) doesn't retry in lockstep. 0 disables jitter.
RETRY_JITTER_FRACTION = max(0.0, min(1.0, float(os.getenv("SCHEDULER_RETRY_JITTER_FRACTION", "0.2"))))


def compute_retry_backoff_delay(base_delay_seconds: int, retry_attempt: int) -> int:
    """Exponential backoff for scheduler-level job retries.

    base_delay_seconds doubles per retry attempt, capped at RETRY_BACKOFF_CAP_SECONDS.
    retry_attempt is 1-indexed (the attempt about to run), so a job's first retry keeps its
    configured base delay unchanged -- only a second or later retry actually backs off. A
    base_delay_seconds of 0 (the default -- immediate retry) stays 0 regardless of attempt.
    """
    if base_delay_seconds <= 0:
        return 0
    multiplier = 2 ** max(retry_attempt - 1, 0)
    return min(base_delay_seconds * multiplier, RETRY_BACKOFF_CAP_SECONDS)


def apply_retry_jitter(delay_seconds: int, rng=random.random) -> int:
    """Spread a backoff delay by +/- RETRY_JITTER_FRACTION (never past the cap).

    A zero delay (immediate retry) stays zero. `rng` returns a float in [0, 1) and is
    injectable so tests are deterministic.
    """
    if delay_seconds <= 0 or RETRY_JITTER_FRACTION <= 0:
        return max(delay_seconds, 0)
    factor = 1 + (rng() * 2 - 1) * RETRY_JITTER_FRACTION
    return min(max(int(round(delay_seconds * factor)), 0), RETRY_BACKOFF_CAP_SECONDS)
