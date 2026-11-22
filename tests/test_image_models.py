import io
import json
from collections import Counter
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from app import ai, image_models as images
from app.image_geometry import Component, Scene, build_model
from app.main import app
from app.mesh_unfolder import load_mesh, unfold

client=TestClient(app)
HTTP_CLIENT=httpx.AsyncClient
SCENE={"components":[{"shape":"box","name":"壁","position":[0,0,0],"size":[40,60,30],"color":"#c9b38b"},{"shape":"gable_roof","name":"屋根","position":[0,60,0],"size":[44,20,34],"color":"#a03524"}],"notes":["裏側と寸法は推定です。"]}


def jpeg():
    buf=io.BytesIO();Image.new('RGB',(24,24),'#887766').save(buf,format='JPEG');return buf.getvalue()


@pytest.fixture(autouse=True)
def isolate():
    images._images.clear()
    yield
    images._images.clear()


def seed(preview=True):
    key='a'*32
    meta={'id':key,'title':'建物の写真','source_url':'https://commons.wikimedia.org/wiki/File:House.jpg','author':'Photographer','license':'CC BY-SA 4.0','preview_url':f'/api/image-model/images/{key}/preview'}
    images._images[key]=images.ImageChoice(key,__import__('time').time(),meta,'https://upload.wikimedia.org/wikipedia/commons/a/ab/House.jpg',jpeg() if preview else None)
    return key


@pytest.mark.parametrize('shape',['box','gable_roof','cylinder','cone'])
@pytest.mark.parametrize('ratio',[0,.5,1])
def test_primitives_have_closed_triangles_and_correct_height(shape,ratio):
    part=Component(shape=shape,position=(0,0,0),size=(40,70,30),top_ratio=ratio)
    result=build_model(Scene(components=[part]),120)
    mesh=load_mesh(result['obj'].encode(),'image.obj')
    edges=Counter(tuple(sorted((a,b))) for face in mesh.faces for a,b in zip(face,(face[1],face[2],face[0])))
    assert set(edges.values())=={2}
    assert 0<len(mesh.faces)<=500
    assert result['size_mm'][1]==120
    assert unfold(mesh,unit='mm',scale=1,glue_tabs=False).parts


@pytest.mark.parametrize('bad',[{'size':[0,10,10]},{'size':[float('inf'),10,10]},{'position':[float('nan'),0,0]},{'shape':'arbitrary_mesh'},{'sides':100},{'color':'url(secret)'},{'script':'execute'}])
def test_invalid_model_components_are_rejected(bad):
    with pytest.raises((ValidationError,ValueError)):
        part=Component(**({'shape':'box','position':[0,0,0],'size':[20,30,40]}|bad))
        build_model(Scene(components=[part]),120)


@pytest.mark.parametrize('provider',['openai','gemini','anthropic','ollama','local_openai'])
def test_consented_vision_produces_obj_and_existing_mesh_engine_can_unfold(monkeypatch,provider):
    image_id=seed();sent=[]
    def handler(request):
        sent.append(request);raw=json.dumps(SCENE,ensure_ascii=False)
        body={'openai':{'output':[{'content':[{'type':'output_text','text':raw}]}]},'gemini':{'candidates':[{'content':{'parts':[{'text':raw}]}}]},'anthropic':{'content':[{'type':'text','text':raw}]},'ollama':{'message':{'content':raw}},'local_openai':{'choices':[{'message':{'content':raw}}]}}[provider]
        return httpx.Response(200,json=body)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:HTTP_CLIENT(transport=httpx.MockTransport(handler),**kw))
    headers={'X-AI-Provider':provider,'X-AI-Model':'vision-model','X-AI-Key':'test-vision-key'}
    if provider in ai.LOCAL_PROVIDERS:headers|={'X-AI-Endpoint':'http://localhost:11434' if provider=='ollama' else 'http://localhost:1234/v1','X-AI-Vision':'true'}
    r=client.post('/api/image-model/generate',json={'image_id':image_id,'name':'画像の建物','height_mm':100,'consent':True},headers=headers)
    assert r.status_code==200,r.text
    data=r.json();assert client.get(data['saved_model']['obj_url']).content==data['obj'].encode()
    assert data['saved_model']['glb_url'] is None
    assert data['estimated'] is True and len(data['components'])==2 and data['size_mm'][1]==100
    assert 'test-vision-key' not in r.text
    assert 'commons.wikimedia.org' in data['obj'] and 'CC BY-SA' in data['obj']
    mesh=load_mesh(data['obj'].encode(),'generated.obj')
    assert len(mesh.faces)==20 and unfold(mesh,unit='mm',scale=1,glue_tabs=False).parts
    assert len(sent)==1
    body=json.loads(sent[0].content)
    encoded=__import__('base64').b64encode(images._images[image_id].preview).decode()
    assert encoded in json.dumps(body)
    assert r.headers['cache-control']=='no-store'
    assert 'test-vision-key' not in repr(images._images)


def test_no_consent_or_no_vision_never_sends_image(monkeypatch):
    seed()
    def forbidden(**kw):raise AssertionError('No network permitted')
    monkeypatch.setattr(ai.httpx,'AsyncClient',forbidden)
    assert client.post('/api/image-model/generate',json={'image_id':'a'*32}).status_code==400
    headers={'X-AI-Provider':'ollama','X-AI-Model':'text-only','X-AI-Endpoint':'http://localhost:11434'}
    assert client.post('/api/image-model/generate',json={'image_id':'a'*32,'consent':True},headers=headers).status_code==400
    assert client.post('/api/image-model/generate',json={'image_id':'a'*32,'consent':True}).status_code==400


def test_image_search_metadata_and_safe_preview_loading(monkeypatch):
    calls=[]
    info={'mime':'image/jpeg','thumburl':'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/House.jpg/640px-House.jpg?tracking=remove','descriptionurl':'https://commons.wikimedia.org/wiki/File:House.jpg','extmetadata':{'Artist':{'value':'<b>Photographer</b>'},'LicenseShortName':{'value':'CC BY-SA 4.0'}}}
    def handler(request):
        calls.append(request)
        if request.url.host=='commons.wikimedia.org':return httpx.Response(200,json={'query':{'pages':{'1':{'title':'File:House.jpg','imageinfo':[info]}}}})
        assert request.url.host=='thumb.wikimedia.org'
        assert not request.url.query
        return httpx.Response(200,content=jpeg())
    monkeypatch.setattr(images.httpx,'AsyncClient',lambda **kw:HTTP_CLIENT(transport=httpx.MockTransport(handler),**kw))
    r=client.get('/api/image-model/images?q=house');assert r.status_code==200
    item=r.json()['images'][0]
    assert item['author']=='Photographer'
    r=client.get(item['preview_url']);assert r.status_code==200 and r.headers['content-type'].startswith('image/jpeg')
    assert len(calls)==2
    client.get(item['preview_url']);assert len(calls)==3


@pytest.mark.parametrize('url',['http://upload.wikimedia.org/wikipedia/commons/a/b.jpg','https://evil.test/wikipedia/commons/a.jpg','https://user:secret@upload.wikimedia.org/wikipedia/commons/a.jpg','https://upload.wikimedia.org:443/wikipedia/commons/a.jpg','https://upload.wikimedia.org/private/file.jpg'])
def test_unapproved_image_urls_are_rejected(url):
    with pytest.raises(ValueError):images.image_url(url)


def test_invalid_ai_response_is_error_not_a_fabricated_model(monkeypatch):
    seed()
    def handler(request):return httpx.Response(200,json={'output':[{'content':[{'type':'output_text','text':'test-secret invalid output'}]}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kw:HTTP_CLIENT(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/image-model/generate',json={'image_id':'a'*32,'consent':True},headers={'X-AI-Provider':'openai','X-AI-Model':'test','X-AI-Key':'test-secret'})
    assert r.status_code==502 and 'test-secret' not in r.text and 'obj' not in r.json()
