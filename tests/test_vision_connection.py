import base64
import io
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app import ai
from app.main import app

client=TestClient(app)


def headers(provider='openai'):
    values={'X-AI-Provider':provider,'X-AI-Model':'vision-model','X-AI-Key':'test-vision-key','X-AI-Test-Mode':'image'}
    if provider in ai.LOCAL_PROVIDERS:values['X-AI-Endpoint']='http://localhost:11434' if provider=='ollama' else 'http://localhost:1234/v1'
    return values


def payload(provider,raw):
    return {'openai':{'output':[{'content':[{'type':'output_text','text':raw}]}]},'gemini':{'candidates':[{'content':{'parts':[{'text':raw}]}}]},'anthropic':{'content':[{'type':'text','text':raw}]},'ollama':{'message':{'content':raw}},'local_openai':{'choices':[{'message':{'content':raw}}]}}[provider]


@pytest.mark.parametrize('provider',['openai','gemini','anthropic','ollama','local_openai'])
def test_synthetic_image_reading_is_verified_for_every_provider(monkeypatch,provider):
    encoded,expected=ai.vision_probe()
    monkeypatch.setattr(ai,'vision_probe',lambda:(encoded,expected))
    original=httpx.AsyncClient;sent=[]
    def handler(request):
        sent.append(request);return httpx.Response(200,json=payload(provider,' '.join(expected)))
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/ai/test',headers=headers(provider),json={'private_material':'must-not-be-sent'})
    assert r.status_code==200 and r.json()['ok'] is True and r.json()['vision_tested'] is True
    assert '色の認識' in r.json()['message'] and r.headers['cache-control']=='no-store'
    body=json.loads(sent[0].content)
    assert encoded in json.dumps(body)
    assert 'must-not-be-sent' not in json.dumps(body) and 'test-vision-key' not in json.dumps(body)
    if provider=='ollama':assert body['think'] is False
    if provider=='openai':assert body['store'] is False
    assert 'test-vision-key' not in r.text


@pytest.mark.parametrize('answer',['OK','BLUE RED','I cannot see an image','RED BLUE GREEN','test-vision-key'])
def test_status_200_is_not_enough_if_image_colors_are_not_recognized(monkeypatch,answer):
    encoded,_=ai.vision_probe();monkeypatch.setattr(ai,'vision_probe',lambda:(encoded,('RED','BLUE')))
    original=httpx.AsyncClient
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload('openai',answer))),**kw))
    response=client.post('/api/ai/test',headers=headers())
    assert response.status_code==422 and response.json()['vision_tested'] is False
    assert 'test-vision-key' not in response.text


def test_probe_image_is_small_and_contains_the_expected_two_colors():
    encoded,colors=ai.vision_probe()
    assert len(colors)==2 and colors[0]!=colors[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.format=='JPEG' and image.size==(128,64)
        assert image.getpixel((16,32))!=image.getpixel((100,32))


def test_unknown_test_mode_does_not_contact_the_provider(monkeypatch):
    def forbidden(**kw):raise AssertionError('No network')
    monkeypatch.setattr(ai.httpx,'AsyncClient',forbidden)
    config=headers();config['X-AI-Test-Mode']='unsupported'
    assert client.post('/api/ai/test',headers=config).status_code==400
