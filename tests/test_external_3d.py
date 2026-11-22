import asyncio
import json
import struct
import httpx
import pytest
import trimesh
from fastapi.testclient import TestClient
from app import external_3d as ext, image_models
from app.main import app

client=TestClient(app)
ORIGINAL=httpx.AsyncClient


def config(provider='meshy'):
    return {'X-3D-Provider':provider,'X-3D-Model':ext.MODELS[provider][0],'X-3D-Key':'test-only-key'}

@pytest.mark.parametrize('provider',['meshy','tripo','huggingface'])
def test_read_only_connection_checks_never_generate(monkeypatch,provider):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json={'code':0,'data':{'balance':100}} if provider=='tripo' else {'name':'user'} if provider=='huggingface' else {'balance':100})
    monkeypatch.setattr(ext.httpx,'AsyncClient',lambda **kw:ORIGINAL(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/3d/test',headers=config(provider))
    assert r.status_code==200 and r.json()['ok'] is True
    assert len(calls)==1 and calls[0].method=='GET'
    assert 'test-only-key' not in str(calls[0].url) and 'test-only-key' not in r.text

@pytest.mark.parametrize('provider',['meshy','tripo'])
def test_paid_generation_created_once_and_mesh_returns_only_to_browser(monkeypatch,provider,tmp_path):
    calls=[];glb=trimesh.creation.box().export(file_type='glb')
    async def preview(item):return b'safe-jpeg'
    monkeypatch.setattr(image_models,'choice',lambda _:type('Choice',(),{'metadata':{'title':'source'}})())
    monkeypatch.setattr(image_models,'preview',preview)
    def handler(req):
        calls.append(req)
        if req.url.host in {'assets.meshy.ai','cdn.tripo3d.ai'}:
            assert 'authorization' not in req.headers
            return httpx.Response(200,content=glb)
        if req.url.path.endswith('/files'):return httpx.Response(200,json={'code':0,'data':{'file_token':'file_source'}})
        if req.method=='POST':return httpx.Response(200,json={'result':'task_1'} if provider=='meshy' else {'code':0,'data':{'task_id':'task_1'}})
        return httpx.Response(200,json={'status':'SUCCEEDED','model_urls':{'glb':'https://assets.meshy.ai/output.glb'}} if provider=='meshy' else {'code':0,'data':{'status':'success','output':{'model_url':'https://cdn.tripo3d.ai/output.glb'}}})
    monkeypatch.setattr(ext.httpx,'AsyncClient',lambda **kw:ORIGINAL(transport=httpx.MockTransport(handler),**kw))
    r=client.post('/api/3d/generate',headers=config(provider),json={'image_id':'a'*32,'consent':True,'cost_consent':True,'height_mm':100})
    assert r.status_code==200,r.text
    d=r.json();assert len(d['faces'])==12 and d['size_mm'][1]==100
    assert 'test-only-key' not in r.text
    assert len([r for r in calls if r.method=='POST' and not r.url.path.endswith('/files')])==1
    assert not list(tmp_path.rglob('*'))
    body=json.loads(next(r for r in calls if r.method=='POST' and not r.url.path.endswith('/files')).content)
    assert (body['should_texture'] if provider=='meshy' else body['texture']) is False


def test_hf_queue_preserves_session_state_and_fixed_download_host(monkeypatch):
    names=['start_session','preprocess_image','image_to_3d','extract_glb','end_session'];sessions=[];events={};calls=[]
    def handler(req):
        calls.append(req)
        if req.url.path=='/config':return httpx.Response(200,json={'dependencies':[{'id':i,'api_name':n} for i,n in enumerate(names)]})
        if req.url.path.endswith('/upload'):return httpx.Response(200,json=['/tmp/gradio/input.jpg'])
        if req.url.path.endswith('/queue/join'):
            body=json.loads(req.content);sessions.append(body['session_hash']);events[body['session_hash']]=body['fn_index']
            return httpx.Response(200,json={'event_id':str(body['fn_index'])})
        if req.url.path.endswith('/queue/data'):
            i=events[req.url.params['session_hash']]
            data=[{'path':'/tmp/gradio/input.jpg'}] if i==1 else [{'path':'/tmp/outputs/result.glb','url':'https://evil.test/no.glb'}] if i==3 else []
            return httpx.Response(200,text='data: '+json.dumps({'event_id':str(i),'msg':'process_completed','success':True,'output':{'data':data}})+'\n\n')
        assert req.url.host=='microsoft-trellis-2.hf.space' and '/gradio_api/file=' in req.url.path
        return httpx.Response(200,content=b'glb')
    async def run():
        async with ORIGINAL(transport=httpx.MockTransport(handler)) as c:return await ext.generate(c,'huggingface','TRELLIS.2','',b'jpeg')
    assert asyncio.run(run())==b'glb'
    assert len(set(sessions))==1 and len(sessions)==5
    assert calls[-2].url.path.endswith('/queue/join') # remote session cleanup


@pytest.mark.parametrize('url',['http://assets.meshy.ai/x','https://127.0.0.1/x','https://assets.meshy.ai.evil.test/x','https://user:pass@assets.meshy.ai/x'])
def test_unapproved_model_download_never_contacts_host(url):
    async def run():
        async with ORIGINAL(transport=httpx.MockTransport(lambda _:pytest.fail('Network forbidden'))) as c:
            with pytest.raises(ValueError):await ext.download(c,url,'meshy')
    asyncio.run(run())


def test_mesh_simplification_and_external_buffer_rejection():
    blob=trimesh.creation.icosphere(subdivisions=3).export(file_type='glb')
    model=ext.mesh_result(blob,120)
    assert len(model['faces'])<=400 and model['size_mm'][1]==120
    n=struct.unpack_from('<I',blob,12)[0];tree=json.loads(blob[20:20+n]);tree['buffers'][0]['uri']='file:///private/source'
    raw=json.dumps(tree).encode();raw+=b' '*((-len(raw))%4);rest=blob[20+n:]
    evil=struct.pack('<4sIIII',b'glTF',2,20+len(raw)+len(rest),len(raw),0x4e4f534a)+raw+rest
    with pytest.raises(ValueError,match='External buffers'):ext.mesh_result(evil,120)


def test_consent_and_unknown_models_do_not_generate(monkeypatch):
    monkeypatch.setattr(ext.httpx,'AsyncClient',lambda **kw:pytest.fail('Network forbidden'))
    r=client.post('/api/3d/generate',headers=config(),json={'image_id':'a'*32,'consent':True})
    assert r.status_code==400
    h=config();h['X-3D-Model']='text-only'
    assert client.post('/api/3d/test',headers=h).status_code==400


def test_errors_never_include_key_or_source(monkeypatch):
    monkeypatch.setattr(ext.httpx,'AsyncClient',lambda **kw:ORIGINAL(transport=httpx.MockTransport(lambda req:httpx.Response(401,text='test-only-key private-source')),**kw))
    r=client.post('/api/3d/test',headers=config())
    assert r.status_code==502 and 'test-only-key' not in r.text and 'private-source' not in r.text
