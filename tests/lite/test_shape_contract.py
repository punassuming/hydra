"""Pin lite API responses to the main edition's pydantic models.

hydra-ctl (and other clients) consume the shapes defined by ``scheduler.models``. If main adds or renames a
field, or lite stops emitting one, these fail instead of silently diverging.
"""

from conftest import py_job, wait_for

from scheduler.models.job_definition import JobDefinition
from scheduler.models.job_run import JobRun
from scheduler.models.worker_info import WorkerInfo


def _aliased_fields(model) -> set[str]:
    return {f.alias or name for name, f in model.model_fields.items()}


def test_job_response_has_every_main_job_field_and_validates(client):
    job = client.post("/jobs/", json=py_job("shape", "pass", schedule={"mode": "cron", "cron": "0 0 1 1 *"})).json()
    missing = _aliased_fields(JobDefinition) - set(job)
    assert not missing, f"lite job response lacks main fields: {sorted(missing)}"
    JobDefinition.model_validate(job)  # also parses with main's own model
    listed = client.get("/jobs/").json()[0]
    assert not (_aliased_fields(JobDefinition) - set(listed))


def test_run_response_has_every_main_run_field_and_validates(client):
    job = client.post("/jobs/", json=py_job("shape-run", "print('x')")).json()
    run_id = wait_for(lambda: client.get(f"/jobs/{job['_id']}/runs").json())[0]["_id"]
    wait_for(lambda: client.get(f"/runs/{run_id}").json()["status"] == "success")
    for run in (
        client.get(f"/runs/{run_id}").json(),
        client.get("/history/").json()[0],
        client.get(f"/jobs/{job['_id']}/runs").json()[0],
    ):
        missing = _aliased_fields(JobRun) - set(run)
        assert not missing, f"lite run response lacks main fields: {sorted(missing)}"
        JobRun.model_validate(run)


def test_worker_response_has_every_main_worker_field(client):
    worker = client.get("/workers/").json()[0]
    missing = _aliased_fields(WorkerInfo) - set(worker)
    assert not missing, f"lite worker response lacks main fields: {sorted(missing)}"
    WorkerInfo.model_validate(worker)
