import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app
from app.model_capabilities import image_scene_candidate as eligible

@pytest.mark.parametrize('provider,model,item,expected',[
 ('openai','gpt-4o-mini-2024-07-18',{},True),
 ('openai','gpt-6.2-astra',{},True),
 ('openai','gpt-4o-audio-preview',{},False),
 ('openai','gpt-image-1',{},False),
 ('openai','gpt-3.5-turbo',{},False),
 ('openai','unknown-vision-3d',{},False),
 ('openai','gpt-4o',{'capabilities':{'image_input':{'supported':False}}},False),
 ('gemini','gemini-2.5-flash',{'supportedGenerationMethods':['generateContent']},True),
 ('gemini','gemini-2.5-flash-preview-tts',{'supportedGenerationMethods':['generateContent']},False),
 ('gemini','gemini-2.5-flash',{'supportedGenerationMethods':['embedContent']},False),
 ('anthropic','future-model',{'capabilities':{'image_input':{'supported':True}}},True),
 ('anthropic','claude-sonnet-4-5',{'capabilities':{'image_input':{'supported':False}}},False),
 ('local_openai','vision-3d',{},False),
 ('local_openai','custom-alias',{'type':'vlm'},True),
 ('ollama','custom-alias',{'capabilities':['vision','completion']},True),
 ('ollama','llava',{'capabilities':['completion']},False),
 ('ollama','embed',{'capabilities':['vision','embedding']},False),
])
def test_only_image_language_candidates(provider,model,item,expected):
    assert eligible(provider,model,item) is expected

@pytest.mark.parametrize('provider',['ollama','local_openai'])
def test_local_metadata_filters_aliases_and_unknown_models(monkeypatch,provider):
    original=httpx.AsyncClient;requests=[]
    def handler(req):
        requests.append(req)
        if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':n} for n in ['custom','text','broken']]})
        if req.url.path=='/api/show':
            n=json.loads(req.content)['model']
            if n=='broken':return httpx.Response(500)
            return httpx.Response(200,json={'capabilities':['completion','vision'] if n=='custom' else ['completion']})
        if req.url.path=='/v1/models':return httpx.Response(200,json={'data':[{'id':n} for n in ['custom','text','unknown']]})
        assert req.url.path=='/api/v0/models'
        return httpx.Response(200,json={'data':[{'id':'custom','type':'vlm'},{'id':'text','type':'llm'},{'id':'not-listed','type':'vlm'}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=TestClient(app).post('/api/ai/models',headers={'X-AI-Provider':provider,'X-AI-Model-Purpose':'image3d','X-AI-Endpoint':'http://localhost:11434' if provider=='ollama' else 'http://localhost:1234/v1'})
    assert r.status_code==200 and [m['id'] for m in r.json()['models']]==['custom']
    assert all(req.url.host=='localhost' for req in requests)
    assert not any('/chat' in req.url.path for req in requests)

@pytest.mark.parametrize('provider',['openai','ollama'])
def test_general_catalogue_keeps_text_models_but_simple3d_filters_them(monkeypatch,provider):
    original=httpx.AsyncClient;calls=[]
    def handler(req):
        calls.append(req)
        if req.url.path=='/api/show':
            name=json.loads(req.content)['model']
            return httpx.Response(200,json={'capabilities':['completion','vision'] if name=='custom-vision' else ['completion']})
        return httpx.Response(200,json={'data':[{'id':'gpt-3.5-turbo'},{'id':'gpt-4.1-mini'}]} if provider=='openai' else {'models':[{'name':'custom-vision'},{'name':'text-only'}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    h={'X-AI-Provider':provider,'X-AI-Key':'test-key'}
    if provider=='ollama':h['X-AI-Endpoint']='http://localhost:11434'
    c=TestClient(app)
    general=c.post('/api/ai/models',headers=h)
    assert len(general.json()['models'])==2 and len(calls)==1
    vision=c.post('/api/ai/models',headers={**h,'X-AI-Model-Purpose':'image3d'})
    assert [m['id'] for m in vision.json()['models']]==(['gpt-4.1-mini'] if provider=='openai' else ['custom-vision'])
    assert c.post('/api/ai/models',headers={**h,'X-AI-Model-Purpose':'invalid'}).status_code==400
