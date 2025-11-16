from scheduler.utils.affinity import passes_affinity
from scheduler.utils.selectors import select_best_worker
from scheduler.models.job_definition import JobDefinition, Affinity, ScheduleConfig
from scheduler.models.executor import ShellExecutor, PythonExecutor
from scheduler.api.jobs import _validate_job_definition
from scheduler.utils.schedule import initialize_schedule, advance_schedule
from datetime import datetime


def test_affinity_matching():
    job = {"user": "alice", "affinity": {"os": ["linux"], "tags": ["gpu"], "allowed_users": ["alice"]}}
    worker_ok = {"os": "linux", "tags": ["cpu", "gpu"], "allowed_users": ["alice"], "max_concurrency": 2, "current_running": 0}
    worker_bad_os = {"os": "windows", "tags": ["gpu"], "allowed_users": ["alice"], "max_concurrency": 2, "current_running": 0}
    worker_bad_user = {"os": "linux", "tags": ["gpu"], "allowed_users": ["bob"], "max_concurrency": 2, "current_running": 0}

    assert passes_affinity(job, worker_ok)
    assert not passes_affinity(job, worker_bad_os)
    assert not passes_affinity(job, worker_bad_user)


def test_select_best_worker_lowest_load():
    ws = [
        {"worker_id": "w1", "max_concurrency": 4, "current_running": 2},
        {"worker_id": "w2", "max_concurrency": 2, "current_running": 0},
        {"worker_id": "w3", "max_concurrency": 8, "current_running": 7},
    ]
    best = select_best_worker(ws)
    assert best["worker_id"] == "w2"


def test_validate_job_definition_supports_shell_and_python():
    job_shell = JobDefinition(name="shell", user="a", affinity=Affinity(), executor=ShellExecutor(script="echo hi"))
    result_shell = _validate_job_definition(job_shell)
    assert result_shell.valid

    job_py = JobDefinition(name="py", user="a", affinity=Affinity(), executor=PythonExecutor(code="print('hello')"))
    result_py = _validate_job_definition(job_py)
    assert result_py.valid


def test_validate_job_definition_catches_python_syntax():
    job_py = JobDefinition(name="py", user="a", affinity=Affinity(), executor=PythonExecutor(code="print('oops'"))
    result_py = _validate_job_definition(job_py)
    assert not result_py.valid


def test_validation_fails_for_bad_interval():
    job = JobDefinition(
        name="interval",
        user="a",
        affinity=Affinity(),
        executor=ShellExecutor(script="echo hi"),
        schedule=ScheduleConfig(mode="interval", interval_seconds=0, enabled=True),
    )
    result = _validate_job_definition(job)
    assert not result.valid


def test_initialize_interval_schedule_sets_next_run():
    schedule = ScheduleConfig(mode="interval", interval_seconds=60, enabled=True)
    initialized = initialize_schedule(schedule, datetime.utcnow())
    assert initialized.next_run_at is not None


def test_advance_schedule_disables_after_end():
    now = datetime.utcnow()
    schedule = ScheduleConfig(mode="interval", interval_seconds=10, enabled=True, next_run_at=now, end_at=now)
    advanced = advance_schedule(schedule)
    assert advanced.next_run_at is None
    assert not advanced.enabled
