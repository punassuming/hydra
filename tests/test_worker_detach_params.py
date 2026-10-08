import json
from unittest.mock import MagicMock

from scheduler.api.workers import _requeue_worker_queue


def test_detach_requeue_preserves_run_params():
    r = MagicMock()
    envelope = {"job_id": "job-1", "job": {"priority": 7}, "params": {"FOO": "bar"}, "enqueued_ts": 5.0}
    r.lrange.return_value = [json.dumps(envelope)]

    assert _requeue_worker_queue(r, "prod", "worker-1") == 1

    r.zadd.assert_called_once_with("job_queue:prod:pending", {"job-1": 7.0})
    mapping = r.hset.call_args.kwargs["mapping"]
    assert json.loads(mapping["params"]) == {"FOO": "bar"}
    assert mapping["reason"] == "worker_detached"
    r.delete.assert_called_once_with("job_queue:prod:worker-1")
