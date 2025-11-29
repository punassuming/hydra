import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from scheduler.main import app
from scheduler.api.ai import AIProvider

client = TestClient(app)

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
        completion_mock.choices[0].message.content = '{"name": "mock-job-openai", "executor": {"type": "shell", "script": "echo hi"}}'
        mock.OpenAI.return_value.chat.completions.create.return_value = completion_mock
        yield mock

def test_generate_job_gemini_no_key(mock_gemini):
    # Ensure no env var
    with patch.dict("os.environ", {}, clear=True):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "gemini"})
        assert response.status_code == 500
        assert "GEMINI_API_KEY not configured" in response.json()["detail"]

def test_generate_job_gemini_success(mock_gemini):
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "gemini"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "mock-job"
        mock_gemini.GenerativeModel.assert_called_with("gemini-pro")

def test_generate_job_openai_success(mock_openai):
    with patch.dict("os.environ", {"OPENAI_API_KEY": "fake"}):
        response = client.post("/ai/generate_job", json={"prompt": "test", "provider": "openai"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "mock-job-openai"

def test_analyze_run_gemini(mock_gemini):
    # Setup mock for analyze which returns plain text, not json
    mock_gemini.GenerativeModel.return_value.generate_content.return_value.text = "Analysis: Fix it."
    
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake"}):
        response = client.post("/ai/analyze_run", json={
            "run_id": "1", 
            "stdout": "", 
            "stderr": "err", 
            "exit_code": 1,
            "provider": "gemini"
        })
        assert response.status_code == 200
        assert response.json()["analysis"] == "Analysis: Fix it."

def test_analyze_run_invalid_provider():
    response = client.post("/ai/analyze_run", json={
        "run_id": "1", 
        "stdout": "", 
        "stderr": "err", 
        "exit_code": 1,
        "provider": "unknown"
    })
    # Pydantic validation should catch this or the logic raises 400/422
    assert response.status_code in [400, 422]
