"""No real provider calls or real keys: verify the request-scoped credential boundary."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app

client = TestClient(app)
PAYLOAD = {"place": "小さな洋館"}


def headers(provider="openai", key="test-user-key", model="custom-model"):
    return {"X-AI-Provider": provider, "X-AI-Key": key, "X-AI-Model": model}


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic"])
def test_provider_headers_model_and_no_credential_echo(monkeypatch, provider):
    calls = []
    original = httpx.AsyncClient
    def handler(request):
        calls.append(request)
        text = json.dumps({"proposals": [{"title": "案 test-user-key", "description": "提案", "style": "easy"}], "notes": ["test-user-key"]})
        if provider == "openai":
            response = {"output": [{"content": [{"type": "output_text", "text": text}]}]}
        elif provider == "gemini":
            response = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        else:
            response = {"content": [{"type": "text", "text": text}]}
        return httpx.Response(200, json=response)
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post("/api/proposals", json=PAYLOAD, headers=headers(provider))
    assert result.status_code == 200
    assert result.json()["provider"] == provider
    assert "test-user-key" not in result.text
    assert result.headers["cache-control"] == "no-store"
    req = calls[0]
    assert "test-user-key" not in str(req.url)
    body = json.loads(req.content)
    assert "test-user-key" not in req.content.decode()
    if provider == "gemini":
        assert req.url.path.endswith("/custom-model:generateContent")
        assert req.headers["x-goog-api-key"] == "test-user-key"
    else:
        assert body["model"] == "custom-model"
        assert req.headers["authorization" if provider == "openai" else "x-api-key"].endswith("test-user-key")
    if provider == "openai":
        assert body["store"] is False
    # A different user, then a locked/unconfigured user, cannot inherit these credentials.
    client.post("/api/proposals", json=PAYLOAD, headers=headers(provider, "other-user-key"))
    assert calls[-1].headers[{"openai": "authorization", "gemini": "x-goog-api-key", "anthropic": "x-api-key"}[provider]].endswith("other-user-key")
    assert client.post("/api/proposals", json=PAYLOAD).json()["provider"] == "offline"
    assert len(calls) == 2


def test_no_server_environment_fallback(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "server-key-must-not-be-used")
    assert client.post("/api/proposals", json=PAYLOAD).json()["provider"] == "offline"


@pytest.mark.parametrize("config", [
    {"X-AI-Key": "test-secret"}, headers("unknown"),
    headers(model="../../invalid?key=test-secret"), headers(key="test secret"),
    headers(key="s" * 513),
])
def test_bad_config_is_sanitized(config):
    result = client.post("/api/proposals", json=PAYLOAD, headers=config)
    assert result.status_code == 400
    assert result.json() == {"detail": "AI設定を確認してください。"}
    assert result.headers["cache-control"] == "no-store"


def test_body_validation_does_not_echo_inputs():
    r = client.post("/api/proposals", json={"place": "x", "scale": "test-secret"}, headers=headers())
    assert r.status_code == 422
    assert "test-secret" not in r.text
    assert "test-user-key" not in r.text


@pytest.mark.parametrize("kind", ["auth", "rate", "timeout", "malformed", "shape"])
def test_provider_failure_is_sanitized(monkeypatch, kind):
    original = httpx.AsyncClient
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("test-user-key", request=request)
        if kind in {"auth", "rate"}:
            return httpx.Response(401 if kind == "auth" else 429, text="test-user-key")
        if kind == "shape":
            return httpx.Response(200, json={"output": None})
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "test-user-key"}]}]})
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    response = client.post("/api/proposals", json=PAYLOAD, headers=headers())
    assert response.status_code == 200
    assert response.json()["provider"] == "offline"
    assert "test-user-key" not in response.text


def test_concurrent_credentials_are_not_shared(monkeypatch):
    original = httpx.AsyncClient
    seen = []
    async def handler(request):
        seen.append(request.headers["authorization"])
        await asyncio.sleep(0)
        return httpx.Response(401)
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    async def run():
        req = ai.ProposalRequest(**PAYLOAD)
        await asyncio.gather(*(ai.proposals(req, ai.AICredentials("openai", "test", key)) for key in ["alice", "bob"]))
    asyncio.run(run())
    assert sorted(seen) == ["Bearer alice", "Bearer bob"]
    assert "alice" not in repr(ai.AICredentials("openai", "test", "alice"))
