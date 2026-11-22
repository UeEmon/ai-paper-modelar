import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app

client=TestClient(app)

def headers(provider='openai',key='test-catalogue-key'):
    config={'X-AI-Provider':provider,'X-AI-Key':key}
    if provider in ai.LOCAL_PROVIDERS:
        config['X-AI-Endpoint']='http://localhost:11434' if provider=='ollama' else 'http://localhost:1234/v1'
    return config


@pytest.mark.parametrize('provider',['openai','gemini','anthropic','ollama','local_openai'])
def test_normalized_catalogues_use_get_and_do_not_need_a_model(monkeypatch,provider):
    original=httpx.AsyncClient;sent=[];options=[]
    ids=['org/model:q4','another-model'] if provider in ai.LOCAL_PROVIDERS else ['chat-model','another-model']
    def handler(request):
        sent.append(request)
        if provider=='gemini':
            data={'models':[{'name':'models/'+model,'displayName':model,'supportedGenerationMethods':['generateContent']} for model in ids]+[{'name':'models/embed-only','supportedGenerationMethods':['embedContent']}]}
        elif provider=='ollama':data={'models':[{'name':model} for model in ids]}
        else:data={'data':[{'id':model,'display_name':model} for model in ids]}
        return httpx.Response(200,json=data)
    def fake(**kw):options.append(kw);return original(transport=httpx.MockTransport(handler),**kw)
    monkeypatch.setattr(ai.httpx,'AsyncClient',fake)
    config=headers(provider,'' if provider in ai.LOCAL_PROVIDERS else 'test-catalogue-key')
    config['X-AI-Model']='not a valid model id'
    r=client.post('/api/ai/models',headers=config)
    assert r.status_code==200 and r.json()['ok'] is True
    assert [m['id'] for m in r.json()['models']]==sorted(ids)
    assert r.headers['cache-control']=='no-store'
    req=sent[0];assert req.method=='GET' and not req.content
    assert 'test-catalogue-key' not in str(req.url)
    assert req.url.path=={'openai':'/v1/models','gemini':'/v1beta/models','anthropic':'/v1/models','ollama':'/api/tags','local_openai':'/v1/models'}[provider]
    if provider in ai.LOCAL_PROVIDERS:
        assert 'authorization' not in req.headers
        assert options[0]['trust_env'] is False
    assert options[0]['follow_redirects'] is False


@pytest.mark.parametrize('provider',['gemini','anthropic'])
def test_paginated_catalogues_remain_on_fixed_url_and_deduplicate(monkeypatch,provider):
    original=httpx.AsyncClient;sent=[]
    def handler(request):
        sent.append(request)
        entries=[{'name':'models/second','supportedGenerationMethods':['generateContent']},{'name':'models/first','supportedGenerationMethods':['generateContent']}] if provider=='gemini' else [{'id':'second'},{'id':'first'}]
        if provider=='gemini':
            body={'models':entries if len(sent)==2 else entries[:1]}
            if len(sent)==1:body['nextPageToken']='next-token'
        else:
            body={'data':entries if len(sent)==2 else entries[:1],'has_more':len(sent)==1,'last_id':'second'}
        return httpx.Response(200,json=body)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/models',headers=headers(provider))
    assert [m['id'] for m in r.json()['models']]==['first','second']
    assert len(sent)==2
    assert sent[0].url.host==sent[1].url.host
    assert sent[1].url.params['pageToken' if provider=='gemini' else 'after_id']==('next-token' if provider=='gemini' else 'second')


def test_corrupt_and_secret_model_metadata_are_filtered(monkeypatch):
    original=httpx.AsyncClient
    def handler(request):
        return httpx.Response(200,json={'data':[{'id':'valid','display_name':'test-catalogue-key name'},{'id':'bad\nmodel'},{'id':'test-catalogue-key'},{'id':'x'*121},None,{'id':12}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/models',headers=headers())
    assert [m['id'] for m in r.json()['models']]==['valid']
    assert 'test-catalogue-key' not in r.text


@pytest.mark.parametrize('failure,status',[(401,400),(403,400),(429,400),('timeout',504),('network',502),('invalid',502),('redirect',400)])
def test_catalogue_failures_are_sanitized_and_no_redirects_followed(monkeypatch,failure,status):
    original=httpx.AsyncClient;sent=[]
    def handler(request):
        sent.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('test-catalogue-key',request=request)
        if failure=='network':raise httpx.ConnectError('test-catalogue-key',request=request)
        if failure=='invalid':return httpx.Response(200,json={'data':None})
        if failure=='redirect':return httpx.Response(307,headers={'location':'https://evil.test'})
        return httpx.Response(failure,text='test-catalogue-key')
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/models',headers=headers())
    assert r.status_code==status and r.json()['ok'] is False
    assert 'test-catalogue-key' not in r.text
    assert r.headers['cache-control']=='no-store'
    assert len(sent)==1


def test_models_are_capped_and_page_cycles_stop(monkeypatch):
    original=httpx.AsyncClient;sent=[]
    def handler(request):
        sent.append(request)
        return httpx.Response(200,json={'models':[{'name':'models/chat','supportedGenerationMethods':['generateContent']}],'nextPageToken':'same-token'})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/models',headers=headers('gemini'))
    assert len(sent)==2 and r.json()['truncated'] is True
    def many(request):return httpx.Response(200,json={'data':[{'id':f'model-{i}'} for i in range(1100)]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(many),**kw))
    r=client.post('/api/ai/models',headers=headers())
    assert len(r.json()['models'])==1000 and r.json()['truncated'] is True


def test_missing_credentials_and_unapproved_endpoint_never_contact_provider(monkeypatch):
    def forbidden(**kw):raise AssertionError('Network is forbidden')
    monkeypatch.setattr(ai.httpx,'AsyncClient',forbidden)
    assert client.post('/api/ai/models').status_code==400
    assert client.post('/api/ai/models',headers={'X-AI-Provider':'openai'}).status_code==400
    config=headers('ollama','');config['X-AI-Endpoint']='http://169.254.169.254:80'
    assert client.post('/api/ai/models',headers=config).status_code==400
