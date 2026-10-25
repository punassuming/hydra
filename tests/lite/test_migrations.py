"""Schema migrations and backups. tests/fixtures/lite_v1.db is a frozen v1 database: never regenerate it to make a
test pass - every future migration must upgrade it."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from hydra_lite.store import Store
from hydra_lite.store import store as store_module
from hydra_lite.store.store import latest_version

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lite_v1.db"


@pytest.fixture()
def v1_db(tmp_path):
    dest = tmp_path / "hydra.db"
    shutil.copy(FIXTURE, dest)
    return dest


def _content(path):
    con = sqlite3.connect(path)
    try:
        return {
            "version": con.execute("PRAGMA user_version").fetchone()[0],
            "jobs": [r[0] for r in con.execute("SELECT name FROM jobs")],
            "runs": con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        }
    finally:
        con.close()


def test_the_frozen_v1_database_opens_and_keeps_its_data(v1_db):
    store = Store(v1_db)
    job = store.get_job_by_name("fixture-job")
    assert job["priority"] == 7 and [v["version"] for v in store.list_versions(job["_id"])] == [2, 1]
    [run] = store.list_runs(job_id=job["_id"])
    assert run["status"] == "success" and run["params"] == {"A": "1"}
    assert store.list_workers()[0]["id"] == "fixture-worker" and store.list_schedule_events(job["_id"])
    store.close()
    # every real migration since v1 was applied, after a copy of the original v1 database
    assert _content(v1_db)["version"] == latest_version()
    if latest_version() > 1:
        assert _content(v1_db.with_name("hydra.db.pre-v1.bak")) == {"version": 1, "jobs": ["fixture-job"], "runs": 1}


def test_pending_migration_runs_once_after_a_backup(v1_db, monkeypatch):
    monkeypatch.setattr(store_module, "_migrations", lambda: [(2, "add_note", "ALTER TABLE jobs ADD COLUMN note TEXT;")])
    store = Store(v1_db)
    store.close()
    after = sqlite3.connect(v1_db)
    assert after.execute("PRAGMA user_version").fetchone()[0] == 2
    assert "note" in [r[1] for r in after.execute("PRAGMA table_info(jobs)")]
    after.close()
    backup = v1_db.with_name("hydra.db.pre-v1.bak")
    assert _content(backup) == {"version": 1, "jobs": ["fixture-job"], "runs": 1}
    assert "note" not in [r[1] for r in sqlite3.connect(backup).execute("PRAGMA table_info(jobs)")]
    Store(v1_db).close()  # already at v2: no second run, no new backup
    assert len(list(v1_db.parent.glob("*.bak"))) == 1


def test_failed_migration_rolls_back_and_names_the_backup(v1_db, monkeypatch):
    bad = "ALTER TABLE jobs ADD COLUMN half_done TEXT; INSERT INTO nope VALUES (1);"
    monkeypatch.setattr(store_module, "_migrations", lambda: [(2, "broken", bad)])
    with pytest.raises(RuntimeError, match=r"0002_broken failed.*left at v1.*pre-v1\.bak"):
        Store(v1_db)
    con = sqlite3.connect(v1_db)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "half_done" not in [r[1] for r in con.execute("PRAGMA table_info(jobs)")]
    assert v1_db.with_name("hydra.db.pre-v1.bak").exists()


def test_fresh_database_goes_straight_to_latest_without_a_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "_migrations", lambda: [(2, "add_note", "ALTER TABLE jobs ADD COLUMN note TEXT;")])
    Store(tmp_path / "hydra.db").close()
    assert _content(tmp_path / "hydra.db")["version"] == 2 and not list(tmp_path.glob("*.bak"))


def test_shipped_migrations_are_numbered_contiguously():
    versions = [v for v, _, _ in store_module._migrations()]
    assert versions == list(range(2, 2 + len(versions)))
    assert store_module.latest_version() == store_module.BASE_VERSION + len(versions)


def test_a_newer_database_is_left_alone(tmp_path):
    path = tmp_path / "hydra.db"
    Store(path).close()
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=99")
    con.close()
    with pytest.raises(RuntimeError, match="newer than this Hydra"):
        Store(path)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 99


def test_backup_is_consistent_and_independent(tmp_path):
    store = Store(tmp_path / "hydra.db")
    job = store.create_job({"name": "b", "executor": {"type": "shell", "script": "x"}, "schedule": {"mode": "immediate"}})
    for _ in range(25):
        store.enqueue_run(job["_id"])
    out = store.backup_to(tmp_path / "out" / "copy.db")
    store.enqueue_run(job["_id"])  # later writes must not appear in the copy
    copy = Store(out)
    assert len(copy.list_runs(limit=1000)) == 25 and len(store.list_runs(limit=1000)) == 26
    copy.close()
    store.close()
    assert not (tmp_path / "out" / "copy.db-wal").exists()


def test_cli_backup(tmp_path, monkeypatch, capsys):
    from cli.__main__ import main

    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "cfg"))
    assert main(["lite", "backup", str(tmp_path / "b.db")]) == 4  # no database yet
    (tmp_path / "data").mkdir()
    shutil.copy(FIXTURE, tmp_path / "data" / "hydra.db")
    dest = tmp_path / "b.db"
    assert main(["lite", "backup", str(dest)]) == 0 and "schema v1" in capsys.readouterr().out
    assert _content(dest)["jobs"] == ["fixture-job"]
    assert main(["lite", "backup", str(dest)]) == 1 and "already exists" in capsys.readouterr().err
    assert main(["lite", "backup", str(dest), "--force"]) == 0
