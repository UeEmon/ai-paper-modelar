"""Local LLM adapters, consent, and server-controlled destination isolation."""
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import ai
from app.main import app
from app.uploads import add_asset, delete_asset

client = TestClient(app)


def config(provider="ollama", endpoint=None, key="", vision=False):
    return {"X-AI-Provider": provider, "X-AI-Model": "org/model:q4_K_M",
            "X-AI-Endpoint": endpoint or ("http://localhost:11434" if provider == "ollama" else "http://localhost:1234/v1"),
            "X-AI-Key": key, "X-AI-Vision": str(vision).lower()}


@pytest.mark.parametrize("provider", ["ollama", "local_openai"])
@pytest.mark.parametrize("key", ["", "test-local-secret"])
def test_local_adapters(monkeypatch, provider, key):
    sent, options = [], []
    original = httpx.AsyncClient
    def handler(request):
        sent.append(request)
        raw = json.dumps({"proposals": [{"title": "灯台案", "description": "紙で作る", "style": "easy"}], "notes": []})
        body = {"message": {"content": raw}} if provider == "ollama" else {"choices": [{"message": {"content": raw}}]}
        return httpx.Response(200, json=body)
    def fake_client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(ai.httpx, "AsyncClient", fake_client)
    result = client.post("/api/proposals", json={"place": "小さな灯台"}, headers=config(provider, key=key))
    assert result.status_code == 200
    assert result.json()["provider"] == provider
    assert result.json()["proposals"][0]["title"] == "灯台案"  # empty key must not corrupt every string
    assert result.headers["cache-control"] == "no-store"
    request = sent[0]
    assert request.url.path == ("/api/chat" if provider == "ollama" else "/v1/chat/completions")
    assert request.headers.get("authorization") == ("Bearer " + key if key else None)
    body = json.loads(request.content)
    assert body["model"] == "org/model:q4_K_M"
    assert body["stream"] is False
    if provider == "ollama":
        assert body["format"] == "json"
        assert body["options"]["num_predict"] == 1600
    else:
        assert body["max_tokens"] == 1600
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"] == 120


@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254:80/latest/meta-data", "http://example.com:11434",
    "http://localhost:8086", "http://localhost:11434.evil.test:80",
    "http://localhost:11434@evil.test:80", "http://user:password@localhost:11434",
    "http://localhost:11434/api", "http://localhost:11434?secret=value",
    "http://localhost:11434#fragment", "file:///etc/passwd", "http://localhost:99999",
    "http://localhost:11434/../../", "http://localhost:11434/\n",
])
def test_unapproved_urls_cannot_trigger_requests(monkeypatch, endpoint):
    def forbidden(**kw):
        raise AssertionError("Unapproved endpoint was contacted")
    monkeypatch.setattr(ai.httpx, "AsyncClient", forbidden)
    response = client.post("/api/proposals", json={"place": "小さな灯台"}, headers=config(endpoint=endpoint))
    assert response.status_code == 400
    assert response.json() == {"detail": "AI設定を確認してください。"}


def test_server_allowlist_replaces_defaults(monkeypatch):
    monkeypatch.setenv("PAPER_MODELAR_LOCAL_AI_URLS", "http://192.168.1.20:8000/v1, http://localhost:9999/")
    assert ai.local_endpoint("http://192.168.1.20:8000/v1/") == "http://192.168.1.20:8000/v1"
    assert ai.local_endpoint("http://localhost:9999") == "http://localhost:9999"
    with pytest.raises(ValueError):
        ai.local_endpoint("http://localhost:11434")
    monkeypatch.setenv("PAPER_MODELAR_LOCAL_AI_URLS", "")
    with pytest.raises(ValueError):
        ai.local_endpoint("http://localhost:9999")


@pytest.mark.parametrize("provider", ["ollama", "local_openai"])
@pytest.mark.parametrize("consent,vision,expected", [(False, True, 0), (True, False, 0), (True, True, 1)])
def test_local_images_require_both_permissions(monkeypatch, provider, consent, vision, expected):
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
    asset = add_asset(buf.getvalue(), "local-reference.png", "front", "正面")
    original, bodies = httpx.AsyncClient, []
    def handler(request):
        bodies.append(json.loads(request.content))
        raw = json.dumps({"proposals": [{"title": "案", "description": "説明"}], "notes": []})
        return httpx.Response(200, json={"message": {"content": raw}} if provider == "ollama" else {"choices": [{"message": {"content": raw}}]})
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    try:
        response = client.post("/api/proposals", json={"place": "小さな灯台", "upload_ids": [asset.id], "include_uploads": consent}, headers=config(provider, vision=vision))
        data = response.json()
        assert data["analyzed_uploads"] == expected
        user = bodies[0]["messages"][1]
        if provider == "ollama":
            assert len(user.get("images", [])) == expected
        else:
            images = [item for item in user["content"] if item["type"] == "image_url"] if isinstance(user["content"], list) else []
            assert len(images) == expected
        assert ("local-reference.png" in json.dumps(bodies)) is consent
        if consent and not vision:
            assert any("画像送信は無効" in note for note in data["notes"])
    finally:
        delete_asset(asset.id)


@pytest.mark.parametrize("failure", ["redirect", "timeout", "invalid", "missing"])
def test_local_failure_never_falls_back_to_cloud(monkeypatch, failure):
    original, sent = httpx.AsyncClient, []
    def handler(request):
        sent.append(str(request.url))
        if failure == "timeout":
            raise httpx.ReadTimeout("test-local-secret", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://api.openai.com/v1/responses"})
        if failure == "missing":
            return httpx.Response(404, text="test-local-secret")
        return httpx.Response(200, json={"message": {"content": "invalid test-local-secret"}})
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post("/api/proposals", json={"place": "小さな灯台"}, headers=config(key="test-local-secret"))
    assert result.status_code == 200
    assert result.json()["provider"] == "offline"
    assert "test-local-secret" not in result.text
    assert sent == ["http://localhost:11434/api/chat"]
