from unittest.mock import patch

from scheduler.startup import ensure_indexes


class _FakeCollection:
    def __init__(self, name, fail_unique=False):
        self.name = name
        self.fail_unique = fail_unique
        self.created = []

    def create_index(self, keys, unique=False):
        if unique and self.fail_unique:
            raise Exception("E11000 duplicate key error (simulated pre-existing data)")
        self.created.append((keys, unique))


class _FakeDB:
    def __init__(self, fail_unique=False):
        self.job_runs = _FakeCollection("job_runs")
        self.job_definitions = _FakeCollection("job_definitions", fail_unique=fail_unique)
        self.job_versions = _FakeCollection("job_versions")
        self.credentials = _FakeCollection("credentials", fail_unique=fail_unique)
        self.domains = _FakeCollection("domains", fail_unique=fail_unique)


def test_ensure_indexes_creates_expected_job_runs_indexes():
    db = _FakeDB()
    with patch("scheduler.startup.get_db", return_value=db):
        ensure_indexes()

    created_keys = [keys for keys, _unique in db.job_runs.created]
    assert [("domain", 1), ("start_ts", -1), ("_id", -1)] in created_keys
    assert [("job_id", 1), ("status", 1), ("start_ts", -1)] in created_keys
    assert [("domain", 1), ("worker_id", 1), ("start_ts", 1)] in created_keys
    assert [("status", 1)] in created_keys


def test_ensure_indexes_creates_expected_job_definitions_indexes():
    db = _FakeDB()
    with patch("scheduler.startup.get_db", return_value=db):
        ensure_indexes()

    created_keys = [keys for keys, _unique in db.job_definitions.created]
    assert [("domain", 1), ("schedule.enabled", 1), ("schedule.next_run_at", 1)] in created_keys
    assert [("domain", 1), ("created_at", -1)] in created_keys
    assert [("domain", 1), ("depends_on", 1)] in created_keys
    assert ([("domain", 1), ("name", 1)], True) in db.job_definitions.created


def test_ensure_indexes_creates_expected_job_versions_indexes():
    db = _FakeDB()
    with patch("scheduler.startup.get_db", return_value=db):
        ensure_indexes()

    created_keys = [keys for keys, _unique in db.job_versions.created]
    assert [("job_id", 1), ("version", -1)] in created_keys
    assert [("domain", 1), ("changed_at", -1)] in created_keys


def test_ensure_indexes_creates_unique_indexes_on_credentials_and_domains():
    db = _FakeDB()
    with patch("scheduler.startup.get_db", return_value=db):
        ensure_indexes()

    assert ([("domain", 1), ("name", 1)], True) in db.credentials.created
    assert ([("domain", 1)], True) in db.domains.created


def test_ensure_indexes_survives_pre_existing_duplicate_data():
    """A duplicate-key conflict on a unique index must not crash startup."""
    db = _FakeDB(fail_unique=True)
    with patch("scheduler.startup.get_db", return_value=db):
        ensure_indexes()  # must not raise

    # The non-unique performance indexes still get created regardless.
    created_keys = [keys for keys, _unique in db.job_runs.created]
    assert len(created_keys) == 4
