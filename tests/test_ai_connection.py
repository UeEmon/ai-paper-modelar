import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app

client=TestClient(app)

def headers(provider='openai',key='test-connection-key'):
    data={'X-AI-Provider':provider,'X-AI-Model':'test-model','X-AI-Key':key}
    if provider in ai.LOCAL_PROVIDERS:
        data['X-AI-Endpoint']='http://localhost:11434' if provider=='ollama' else 'http://localhost:1234/v1'
    return data


@pytest.mark.parametrize('provider',['openai','gemini','anthropic','ollama','local_openai'])
def test_connection_uses_selected_model_without_user_material(monkeypatch,provider):
    original=httpx.AsyncClient
    sent=[]
    def handler(request):
        sent.append(request)
        data={'openai':{'output':[]},'gemini':{'candidates':[]},'anthropic':{'content':[]},'ollama':{'message':{'content':'OK'}},'local_openai':{'choices':[]}}
        return httpx.Response(200,json=data[provider])
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/test',headers=headers(provider,'' if provider in ai.LOCAL_PROVIDERS else 'test-connection-key'))
    assert r.status_code==200 and r.json()['ok'] is True
    assert r.headers['cache-control']=='no-store'
    req=sent[0];body=json.loads(req.content)
    assert 'test-connection-key' not in req.content.decode()
    assert 'sources' not in body and 'upload_ids' not in body
    if provider=='gemini':assert '/test-model:generateContent' in req.url.path
    else:assert body['model']=='test-model'
    if provider in ai.LOCAL_PROVIDERS:assert 'authorization' not in req.headers


@pytest.mark.parametrize('failure,code,phrase',[(401,400,'認証'),(403,400,'認証'),(404,400,'モデル'),(429,400,'利用上限'),(500,400,'受け付けません'),('timeout',504,'時間切れ'),('network',502,'起動状態'),('invalid',502,'応答'),('redirect',400,'受け付けません')])
def test_connection_errors_do_not_echo_secrets(monkeypatch,failure,code,phrase):
    original=httpx.AsyncClient
    sent=[]
    def handler(request):
        sent.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('test-connection-key',request=request)
        if failure=='network':raise httpx.ConnectError('test-connection-key',request=request)
        if failure=='invalid':return httpx.Response(200,text='test-connection-key')
        if failure=='redirect':return httpx.Response(307,headers={'location':'https://evil.test'})
        return httpx.Response(failure,text='test-connection-key')
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/test',headers=headers())
    assert r.status_code==code and r.json()['ok'] is False
    assert phrase in r.json()['message']
    assert 'test-connection-key' not in r.text
    assert r.headers['cache-control']=='no-store'
    assert len(sent)==1


def test_connection_rejects_unapproved_local_destination_before_network(monkeypatch):
    def forbidden(**kw):raise AssertionError('Network should not be used')
    monkeypatch.setattr(ai.httpx,'AsyncClient',forbidden)
    config=headers('ollama','');config['X-AI-Endpoint']='http://169.254.169.254:80'
    r=client.post('/api/ai/test',headers=config)
    assert r.status_code==400 and r.json()['ok'] is False
    assert '169.254.169.254' not in r.text
    assert client.post('/api/ai/test').status_code==400
