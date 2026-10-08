import json
import time
from typing import Any, Dict


def requeue_meta(envelope: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Enqueue-meta hash for putting a dispatched-but-unstarted envelope back on
    the domain pending queue.

    Keeps the run's ``params`` (the scheduling loop reads them back out of this
    hash when it re-dispatches); without them a failover or worker detach
    silently re-ran the job with its defaults.
    """
    meta: Dict[str, Any] = {
        "enqueued_ts": envelope.get("enqueued_ts") or time.time(),
        "reason": reason,
        "retry_attempt": envelope.get("retry_attempt", 0),
    }
    params = envelope.get("params")
    if params:
        meta["params"] = json.dumps(params)
    return meta
