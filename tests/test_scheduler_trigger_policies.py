"""misfire_policy / overlap_policy in the full edition's trigger and dispatch loops (mocked Redis/Mongo)."""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scheduler.scheduler import _trigger_job, scheduling_loop
from scheduler.utils.schedule import plan_ticks, select_ticks

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class FakeJobs:
    """Just enough of a Mongo collection for find_one_and_update's compare-and-set on schedule.next_run_at."""

    def __init__(self, doc):
        self.doc = doc
        self.updates = 0

    def find_one_and_update(self, query, update, return_document=None):
        if query["_id"] != self.doc["_id"] or self.doc["schedule"]["next_run_at"] != query["schedule.next_run_at"]:
            return None
        self.doc = {**self.doc, "schedule": update["$set"]["schedule"]}
        self.updates += 1
        return self.doc


class FakeRedis:
    def __init__(self, running=False, pending=False):
        self.running, self.pending, self.added = running, pending, []

    def zscore(self, key, member):
        return 1.0 if self.pending else None

    def exists(self, key):
        return 1 if self.running else 0

    def zadd(self, key, mapping):
        self.added.append((key, dict(mapping)))


def job(**schedule):
    sched = {
        "mode": "interval",
        "interval_seconds": 60,
        "next_run_at": NOW - timedelta(minutes=4, seconds=40),
        "enabled": True,
        **schedule,
    }
    return {"_id": "j1", "priority": 7, "schedule": sched}


def fire(doc, r=None, now=NOW):
    db = MagicMock()
    db.job_definitions = FakeJobs(doc)
    r = r or FakeRedis()
    queued = _trigger_job(r, db, "prod", doc, now)
    return queued, r, db.job_definitions


def next_run(coll):
    return coll.doc["schedule"]["next_run_at"]


def test_on_time_tick_queues_one_entry_and_advances():
    queued, r, coll = fire(job(next_run_at=NOW - timedelta(seconds=1)))
    assert queued == 1 and r.added == [("job_queue:prod:pending", {"j1": 7.0})]
    assert next_run(coll) == NOW - timedelta(seconds=1) + timedelta(seconds=60)


def test_run_once_collapses_a_backlog_into_one_run():
    queued, r, coll = fire(job())  # five ticks were missed
    assert queued == 1 and coll.updates == 1 and next_run(coll) > NOW


def test_skip_drops_missed_ticks():
    queued, r, coll = fire(job(misfire_policy="skip"))
    assert queued == 0 and r.added == [] and next_run(coll) > NOW  # the schedule still moves on


def test_catch_up_replays_a_bounded_backlog_one_tick_per_pass():
    doc = job(misfire_policy="catch_up", catch_up_limit=3)
    total = 0
    for _ in range(10):
        queued, _r, coll = fire(doc)
        total += queued
        doc = coll.doc if coll.updates else doc
        if next_run(coll) > NOW:
            break
    assert total == 3 and next_run(coll) > NOW  # 5 ticks were missed; at most catch_up_limit are replayed


def test_catch_up_first_pass_points_the_schedule_at_the_next_backlog_tick():
    queued, _r, coll = fire(job(misfire_policy="catch_up", catch_up_limit=3))
    ticks, _ = plan_ticks(
        __import__("scheduler.models.job_definition", fromlist=["ScheduleConfig"]).ScheduleConfig.model_validate(
            job(misfire_policy="catch_up", catch_up_limit=3)["schedule"]
        ),
        NOW,
    )
    assert queued == 1 and next_run(coll) == ticks[-3 + 1]  # the oldest kept tick was queued; the next one is due next pass


@pytest.mark.parametrize(
    ("policy", "running", "pending", "expect"),
    [
        ("skip", True, False, 0),
        ("skip", False, True, 0),
        ("skip", False, False, 1),
        ("allow", True, True, 1),
        ("queue", True, False, 1),
    ],
)
def test_overlap_policy_at_trigger_time(policy, running, pending, expect):
    queued, r, _ = fire(
        job(next_run_at=NOW - timedelta(seconds=1), overlap_policy=policy), FakeRedis(running=running, pending=pending)
    )
    assert queued == expect and len(r.added) == expect


def test_a_lost_compare_and_set_queues_nothing():
    doc = job()
    db = MagicMock()
    coll = FakeJobs({**doc, "schedule": {**doc["schedule"], "next_run_at": NOW}})  # someone already advanced it
    db.job_definitions = coll
    r = FakeRedis()
    assert _trigger_job(r, db, "prod", doc, NOW) == 0 and r.added == []


def test_the_shared_planner_gives_the_same_answer_the_lite_edition_uses():
    from hydra_lite.scheduling import plan_ticks as lite_plan
    from hydra_lite.scheduling import select_ticks as lite_select

    assert lite_plan is plan_ticks and lite_select is select_ticks


# ------------------------------------------------------------------------------------------- dispatch (queue)


def _dispatch_once(running, overlap_policy):
    stop = threading.Event()
    r = MagicMock()
    calls = {"n": 0}

    def bzpopmax(keys, timeout=2):
        calls["n"] += 1
        if calls["n"] == 1:
            return ("job_queue:prod:pending", "j1", 5.0)
        stop.set()
        return None

    r.bzpopmax.side_effect = bzpopmax
    r.smembers.return_value = {"prod"}
    r.hgetall.return_value = {"enqueued_ts": "100.0", "params": '{"A": "1"}'}
    r.exists.return_value = 1 if running else 0
    db = MagicMock()
    db.job_definitions.find_one.return_value = {
        "_id": "j1",
        "domain": "prod",
        "priority": 5,
        "executor": {"type": "shell"},
        "schedule": {"overlap_policy": overlap_policy},
    }
    with (
        patch("scheduler.scheduler.get_redis", return_value=r),
        patch("scheduler.scheduler.get_db", return_value=db),
        patch("scheduler.scheduler.time.sleep"),
        patch("scheduler.scheduler.list_online_workers", return_value=[]),
        patch("scheduler.scheduler.event_bus"),
    ):
        scheduling_loop(stop)
    return r


def test_overlap_queue_holds_a_job_while_its_previous_run_is_executing():
    r = _dispatch_once(running=True, overlap_policy="queue")
    assert ("job_queue:prod:pending", {"j1": 5.0}) in [(c.args[0], c.args[1]) for c in r.zadd.call_args_list]  # put back
    held = r.hset.call_args.kwargs["mapping"]
    assert held["params"] == '{"A": "1"}' and held["no_worker_count"] == 0  # params kept, not counted as starvation


def test_overlap_queue_does_not_hold_when_nothing_is_running():
    r = _dispatch_once(running=False, overlap_policy="queue")
    held_calls = [c for c in r.hset.call_args_list if c.kwargs.get("mapping", {}).get("reason") == "overlap_queue"]
    assert held_calls == []  # fell through to normal dispatch (here: "no eligible worker", a different requeue)
