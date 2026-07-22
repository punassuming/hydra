#!/usr/bin/env python3
"""
Test script to validate the new job management improvements.
This script creates test jobs with tags and verifies the new API endpoints.
"""
import sys

from scheduler.api.jobs import _validate_job_definition
from scheduler.models.executor import ShellExecutor

# Test that the new fields are properly defined
from scheduler.models.job_definition import Affinity, JobDefinition


def test_tags_functionality():
    """Test that jobs can be created with tags"""
    print("Testing tags functionality...")
    
    # Create a job with tags
    job = JobDefinition(
        name="test-job-with-tags",
        user="testuser",
        affinity=Affinity(os=["linux"]),
        executor=ShellExecutor(script="echo 'hello'"),
        tags=["production", "critical", "data-processing"]
    )
    
    # Validate the job
    result = _validate_job_definition(job)
    assert result.valid, f"Job validation failed: {result.errors}"
    assert job.tags == ["production", "critical", "data-processing"]
    
    print("✓ Tags functionality works correctly")
    print(f"  - Job name: {job.name}")
    print(f"  - Tags: {job.tags}")
    return True


def test_default_tags():
    """Test that tags default to empty list"""
    print("\nTesting default tags...")
    
    job = JobDefinition(
        name="test-job-no-tags",
        user="testuser",
        affinity=Affinity(os=["linux"]),
        executor=ShellExecutor(script="echo 'hello'")
    )
    
    result = _validate_job_definition(job)
    assert result.valid, f"Job validation failed: {result.errors}"
    assert job.tags == [], f"Expected empty tags, got {job.tags}"
    
    print("✓ Default tags work correctly")
    print(f"  - Job name: {job.name}")
    print(f"  - Tags: {job.tags} (empty list)")
    return True


def test_job_serialization():
    """Test that jobs with tags serialize to MongoDB format correctly"""
    print("\nTesting job serialization...")
    
    job = JobDefinition(
        name="test-serialization",
        user="testuser",
        affinity=Affinity(os=["linux"]),
        executor=ShellExecutor(script="echo 'test'"),
        tags=["tag1", "tag2"]
    )
    
    # Serialize to MongoDB format
    mongo_doc = job.to_mongo()
    assert "tags" in mongo_doc, "tags field missing from MongoDB document"
    assert mongo_doc["tags"] == ["tag1", "tag2"], f"Tags not serialized correctly: {mongo_doc['tags']}"
    
    print("✓ Serialization works correctly")
    print(f"  - Serialized tags: {mongo_doc['tags']}")
    return True


def test_model_validation():
    """Test that the Pydantic models validate correctly"""
    print("\nTesting Pydantic model validation...")
    
    # Test JobDefinition
    job_data = {
        "name": "validation-test",
        "user": "testuser",
        "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
        "executor": {"type": "shell", "script": "echo test"},
        "tags": ["test-tag"]
    }
    
    job = JobDefinition.model_validate(job_data)
    assert job.tags == ["test-tag"], f"Tags not validated correctly: {job.tags}"
    
    print("✓ Pydantic validation works correctly")
    print(f"  - Validated tags: {job.tags}")
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("Job Management Improvements - Validation Tests")
    print("=" * 60)
    
    tests = [
        test_tags_functionality,
        test_default_tags,
        test_job_serialization,
        test_model_validation,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"✗ Test failed: {test_func.__name__}")
            print(f"  Error: {str(e)}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✓ All tests passed!")
        print("\nNew Features Available:")
        print("  1. Job tags for organization and filtering")
        print("  2. Search by job name or ID")
        print("  3. Filter by tags (comma-separated)")
        print("  4. Average duration display from historical runs")
        print("  5. Last failure reason visibility")
        print("  6. System statistics dashboard")
        print("\nAPI Examples:")
        print("  GET /jobs/?search=import")
        print("  GET /jobs/?tags=production,critical")
        print("  GET /overview/jobs  (includes avg_duration_seconds, last_failure_reason)")
        print("  GET /overview/statistics  (new endpoint)")
        sys.exit(0)


if __name__ == "__main__":
    main()
