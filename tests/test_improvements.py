"""Regression tests migrated from the former root-level validation script."""

from scheduler.models.executor import ShellExecutor
from scheduler.models.job_definition import Affinity, JobDefinition


def test_job_tags_serialize_to_mongo():
    job = JobDefinition(
        name="test-serialization",
        user="testuser",
        affinity=Affinity(os=["linux"]),
        executor=ShellExecutor(script="echo test"),
        tags=["tag1", "tag2"],
    )

    mongo_document = job.to_mongo()

    assert mongo_document["tags"] == ["tag1", "tag2"]


def test_job_tags_validate_from_api_shape():
    job = JobDefinition.model_validate(
        {
            "name": "validation-test",
            "user": "testuser",
            "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
            "executor": {"type": "shell", "script": "echo test"},
            "tags": ["test-tag"],
        }
    )

    assert job.tags == ["test-tag"]
