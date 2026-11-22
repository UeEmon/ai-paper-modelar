import json
import struct
import httpx
import pytest
import trimesh
from fastapi.testclient import TestClient
from app.main import app
from app import public_models as public

c=TestClient(app);ORIGINAL=httpx.AsyncClient


def gltf_files():
    glb=trimesh.creation.box().export(file_type='glb');n=struct.unpack_from('<I',glb,12)[0]
    tree=json.loads(glb[20:20+n]);binary=glb[28+n:];tree['buffers'][0]['uri']='table.bin'
    tree['images']=[{'uri':'https://evil.test/private.png'}]
    return tree,binary


def setup(monkeypatch):
    tree,binary=gltf_files();calls=[]
    assets={'wooden_table':{'name':'Wooden Table','type':2,'tags':['wood','furniture'],'authors':{'Artist':'All'},'polycount':12},'adjustable_wrench':{'name':'Adjustable Wrench','type':2,'tags':[]},'surface':{'name':'Table Texture','type':1}}
    def handler(req):
        calls.append(req);assert 'authorization' not in req.headers and 'x-ai-key' not in req.headers
        if req.url.host=='api.polyhaven.com':
            if req.url.path=='/assets':return httpx.Response(200,json=assets)
            assert req.url.path=='/files/wooden_table'
            return httpx.Response(200,json={'gltf':{'1k':{'gltf':{'url':'https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/table.gltf','include':{'table.bin':{'url':'https://dl.polyhaven.org/file/ph-assets/Models/gltf/1k/table.bin'}}}}}})
        assert req.url.host=='dl.polyhaven.org'
        if req.url.path.endswith('.gltf'):return httpx.Response(200,json=tree)
        assert req.url.path.endswith('.bin');return httpx.Response(200,content=binary)
    monkeypatch.setattr(public.httpx,'AsyncClient',lambda **kw:ORIGINAL(transport=httpx.MockTransport(handler),**kw))
    return calls,tree


def test_public_catalogue_filters_by_words_translates_common_japanese_and_shows_cc0(monkeypatch):
    calls,_=setup(monkeypatch)
    data=c.get('/api/public-models?q=机').json()
    assert [m['id'] for m in data['models']]==['wooden_table']
    assert data['models'][0]['author']=='Artist' and data['models'][0]['license']=='CC0'
    assert data['models'][0]['source_url']=='https://polyhaven.com/a/wooden_table'
    assert len(calls)==1 and calls[0].url.path=='/assets' # search does not download geometry
    assert len(c.get('/api/public-models').json()['models'])==2 # no textures


def test_public_model_downloads_geometry_only_and_saves_attribution(monkeypatch,tmp_path):
    calls,_=setup(monkeypatch)
    response=c.post('/api/public-models/import',json={'asset_id':'wooden_table','height_mm':100,'consent':True},headers={'X-AI-Key':'private-user-key'})
    assert response.status_code==200,response.text
    data=response.json();assert len(data['faces'])==12 and data['size_mm'][1]==100
    assert data['provider']=='Poly Haven' and 'AIによる生成ではありません' in data['warnings'][0]
    saved=data['saved_model'];assert saved['attribution']['license']=='CC0'
    assert b'# License: CC0' in c.get(saved['obj_url']).content
    assert c.get(saved['glb_url']).status_code==200
    assert len(calls)==4 # assets, file manifest, glTF and bin; never textures
    for path in tmp_path.rglob('*'):
        if path.is_file():assert b'private-user-key' not in path.read_bytes() and b'evil.test' not in path.read_bytes()
    loaded=c.get(saved['preview_url']).json();assert loaded['saved_model']['attribution']['source_url'].endswith('/wooden_table')


def test_consent_and_unknown_asset_do_not_download_models(monkeypatch):
    calls,_=setup(monkeypatch)
    assert c.post('/api/public-models/import',json={'asset_id':'wooden_table'}).status_code==400
    assert not calls
    assert c.post('/api/public-models/import',json={'asset_id':'not-listed','consent':True}).status_code==404
    assert len(calls)==1


@pytest.mark.parametrize('url',['http://dl.polyhaven.org/file/ph-assets/Models/a.bin','https://127.0.0.1/a.bin','https://dl.polyhaven.org.evil.test/file/ph-assets/Models/a.bin','https://user:password@dl.polyhaven.org/file/ph-assets/Models/a.bin','https://dl.polyhaven.org/file/ph-assets/Models/../private.bin'])
def test_public_asset_destinations_are_fixed(url):
    with pytest.raises(ValueError):public.asset_url(url)


@pytest.mark.parametrize('uri',['https://evil.test/a.bin','../../private.bin','file:///private.bin'])
def test_external_buffer_uris_are_not_fetched(monkeypatch,uri):
    calls,tree=setup(monkeypatch);tree['buffers'][0]['uri']=uri
    response=c.post('/api/public-models/import',json={'asset_id':'wooden_table','consent':True})
    assert response.status_code==502
    assert len(calls)==3 and c.get('/api/generated-models').json()['models']==[]


def test_public_search_errors_are_sanitized(monkeypatch):
    monkeypatch.setattr(public.httpx,'AsyncClient',lambda **kw:ORIGINAL(transport=httpx.MockTransport(lambda req:httpx.Response(503,text='upstream-private-error')),**kw))
    response=c.get('/api/public-models?q=table');assert response.status_code==503 and 'upstream-private-error' not in response.text
