"""Run the real OpenAI and google-genai client classes against a stubbed network.

tests/test_ai.py replaces the entire `openai`/`genai` modules with mocks, so it
cannot notice an SDK upgrade that changes constructor arguments, request shape
or response parsing. Here only the HTTP transport is faked: the actual SDK
builds the request and parses the response, exactly as it does in production.
"""

import json

import httpx
import pytest
from fastapi import HTTPException

from scheduler.api import ai


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")


def patch_openai(monkeypatch, handler):
    real = ai.openai.OpenAI
    monkeypatch.setattr(
        ai.openai, "OpenAI", lambda **kw: real(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)
    )


def patch_genai(monkeypatch, handler):
    real = ai.genai.Client

    def factory(**kw):
        options = kw["http_options"]
        kw["http_options"] = ai.genai_types.HttpOptions(
            timeout=options.timeout, httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        return real(**kw)

    monkeypatch.setattr(ai.genai, "Client", factory)


def test_openai_request_shape_and_response_parsing(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hello from stub"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    patch_openai(monkeypatch, handler)
    assert ai._call_openai("the prompt", system="be brief", model_name="gpt-test") == "hello from stub"

    assert seen["path"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer test-openai-key"
    assert seen["body"]["model"] == "gpt-test"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "the prompt"},
    ]
    assert seen["body"]["temperature"] == 0.1
    assert seen["timeout"]["read"] == 30  # the 30s timeout set in _call_openai reaches the transport


def test_openai_http_errors_surface_as_a_500_with_context(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key", "type": "invalid_request_error"}})

    patch_openai(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc:
        ai._call_openai("p")
    assert exc.value.status_code == 500 and "OpenAI Error" in exc.value.detail


def test_gemini_request_shape_and_response_parsing(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": "hello from gemini stub"}]}, "finishReason": "STOP"}
                ]
            },
        )

    patch_genai(monkeypatch, handler)
    assert ai._call_gemini("the prompt", system="be brief", model_name="gemini-test") == "hello from gemini stub"

    assert seen["path"].endswith("/models/gemini-test:generateContent")
    assert seen["key"] == "test-gemini-key"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "the prompt"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "be brief"


def test_gemini_http_errors_surface_as_a_500_with_context(monkeypatch):
    def handler(request):
        return httpx.Response(403, json={"error": {"code": 403, "message": "denied", "status": "PERMISSION_DENIED"}})

    patch_genai(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc:
        ai._call_gemini("p")
    assert exc.value.status_code == 500 and "Gemini Error" in exc.value.detail
