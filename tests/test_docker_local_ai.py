import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app

client=TestClient(app)

@pytest.mark.parametrize('endpoint',['http://localhost:11434','http://127.0.0.1:11434/','http://[::1]:11434'])
def test_standard_docker_loopback_resolves_to_ollama_host(monkeypatch,endpoint):
    monkeypatch.delenv('PAPER_MODELAR_LOCAL_AI_URLS',raising=False)
    monkeypatch.setattr(ai,'in_container',lambda:True)
    assert ai.local_endpoint(endpoint)=='http://host.docker.internal:11434'


def test_native_loopback_stays_native_and_explicit_allowlist_keeps_literal_meaning(monkeypatch):
    monkeypatch.delenv('PAPER_MODELAR_LOCAL_AI_URLS',raising=False)
    monkeypatch.setattr(ai,'in_container',lambda:False)
    assert ai.local_endpoint('http://localhost:11434')=='http://localhost:11434'
    monkeypatch.setattr(ai,'in_container',lambda:True)
    monkeypatch.setenv('PAPER_MODELAR_LOCAL_AI_URLS','http://localhost:11434')
    assert ai.local_endpoint('http://localhost:11434')=='http://localhost:11434'
    with pytest.raises(ValueError):ai.local_endpoint('http://host.docker.internal:11434')


def test_existing_browser_endpoint_fetches_models_from_host_in_docker(monkeypatch):
    monkeypatch.delenv('PAPER_MODELAR_LOCAL_AI_URLS',raising=False)
    monkeypatch.setattr(ai,'in_container',lambda:True)
    original=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json={'capabilities':['completion','vision']} if request.url.path=='/api/show' else {'models':[{'name':'gemma:latest'}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/models',headers={'X-AI-Provider':'ollama','X-AI-Endpoint':'http://localhost:11434'})
    assert r.status_code==200 and r.json()['models'][0]['id']=='gemma:latest'
    assert r.json()['endpoint']=='http://host.docker.internal:11434'
    assert calls==['http://host.docker.internal:11434/api/tags']


def test_runtime_defaults_are_safe_and_do_not_disclose_custom_hosts(monkeypatch):
    monkeypatch.setattr(ai,'in_container',lambda:True)
    monkeypatch.delenv('PAPER_MODELAR_LOCAL_AI_URLS',raising=False)
    r=client.get('/api/ai/local-config')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert r.json()['endpoints']['ollama']=='http://host.docker.internal:11434'
    monkeypatch.setenv('PAPER_MODELAR_LOCAL_AI_URLS','http://192.168.1.22:9000')
    r=client.get('/api/ai/local-config')
    assert r.json()['endpoints']['ollama'] is None and '192.168.1.22' not in r.text
    monkeypatch.setenv('PAPER_MODELAR_LOCAL_AI_URLS','http://host.docker.internal:11434')
    assert client.get('/api/ai/local-config').json()['endpoints']['ollama']=='http://host.docker.internal:11434'
