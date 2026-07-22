import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from scheduler.api.ai import AIProvider
from scheduler.main import app

_TEST_ADMIN_TOKEN = "test-admin-token-ai"

client = TestClient(app)

@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)

def _auth_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}

@pytest.fixture
def mock_gemini():
    with patch("scheduler.api.ai.genai") as mock:
        model_mock = MagicMock()
        model_mock.generate_content.return_value.text = '{"name": "mock-job", "executor": {"type": "shell", "script": "echo hi"}}'
        mock.GenerativeModel.return_value = model_mock
        yield mock

@pytest.fixture
def mock_openai():
    with patch("scheduler.api.ai.openai") as mock:
        completion_mock = MagicMock()
        completion_mock.choices[0].message.content = (
            '{"name": "mock-job-openai", "executor": {"type": "shell", "script": "echo hi"}}'
        )
        mock.OpenAI.return_value.chat.completions.create.return_value = completion_mock
        yield mock

def test_generate_job_gemini_no_key(mock_gemini):
    # Ensure no Gemini env var but keep admin token
    with patch.dict("os.environ", {"ADMIN_TOKEN": _TEST_ADMIN_TOKEN}, clear=True):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "gemini"}, headers=_auth_headers())
        assert response.status_code == 500
        assert "GEMINI_API_KEY not configured" in response.json()["detail"]

def test_generate_job_gemini_success(mock_gemini):
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake", "ADMIN_TOKEN": _TEST_ADMIN_TOKEN}):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "gemini"}, headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "mock-job"
        mock_gemini.GenerativeModel.assert_called_with("gemini-pro")

def test_generate_job_openai_success(mock_openai):
    with patch.dict("os.environ", {"OPENAI_API_KEY": "fake", "ADMIN_TOKEN": _TEST_ADMIN_TOKEN}):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "openai"}, headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "mock-job-openai"

def test_analyze_run_gemini(mock_gemini):
    # Setup mock for analyze which returns plain text, not json
    mock_gemini.GenerativeModel.return_value.generate_content.return_value.text = "Analysis: Fix it."
    
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake", "ADMIN_TOKEN": _TEST_ADMIN_TOKEN}):
        response = client.post("/ai/analyze_run", json={
            "run_id": "1", 
            "stdout": "", 
            "stderr": "err", 
            "exit_code": 1,
            "provider": "gemini"
        }, headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["analysis"] == "Analysis: Fix it."

def test_analyze_run_invalid_provider():
    response = client.post("/ai/analyze_run", json={
        "run_id": "1", 
        "stdout": "", 
        "stderr": "err", 
        "exit_code": 1,
        "provider": "unknown"
    }, headers=_auth_headers())
    # Pydantic validation should catch this or the logic raises 400/422
    assert response.status_code in [400, 422]


def test_predict_duration_returns_estimate():
    class FakeCursor:
        def __init__(self, docs):
            self.docs = docs

        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return self.docs[:n]

    class FakeJobRuns:
        def find(self, *_args, **_kwargs):
            return FakeCursor([{"duration": 10}, {"duration": 20}, {"duration": 40}])

    class FakeDB:
        job_runs = FakeJobRuns()

    with patch("scheduler.api.ai.get_db", return_value=FakeDB()):
        response = client.post("/ai/predict_duration", json={"job_id": "job-1"}, headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["sample_size"] == 3
    assert data["estimated_duration_seconds"] == 20.0
    assert data["p90_duration_seconds"] == 36.0


def test_predict_duration_empty_history():
    class FakeCursor:
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return []

    class FakeJobRuns:
        def find(self, *_args, **_kwargs):
            return FakeCursor()

    class FakeDB:
        job_runs = FakeJobRuns()

    with patch("scheduler.api.ai.get_db", return_value=FakeDB()):
        response = client.post("/ai/predict_duration", json={"job_id": "job-2"}, headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["estimated_duration_seconds"] is None
