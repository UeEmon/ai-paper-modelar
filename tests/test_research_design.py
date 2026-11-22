import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import ai
from app.main import app

client=TestClient(app)
SOURCE={"title":"海辺の灯台","url":"https://ja.wikipedia.org/wiki/灯台","summary":"円形の塔と上部の灯室が特徴。"}
DRAFT={"template":"cone","width_m":4,"depth_m":4,"height_m":16,"top_ratio":0.65,"roof":"flat","overhang_m":0}


def provider(monkeypatch, draft):
    sent=[]
    original=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content);sent.append(body)
        text=json.dumps({"proposals":[{"style":"retro","title":"灯室を強調した灯台","description":"円形の塔を円すい台に簡略化します。","design":draft,"design_basis":"資料にある円形の塔を参考にした推定寸法です。","source_indices":[1,99,True,1]}],"notes":[]})
        return httpx.Response(200,json={"output":[{"content":[{"type":"output_text","text":text}]}]})
    monkeypatch.setattr(ai.httpx,"AsyncClient",lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    return sent


def post():
    return client.post('/api/proposals',json={"place":"海辺の灯台","sources":[SOURCE],"scale":100},headers={"X-AI-Provider":"openai","X-AI-Model":"test-model","X-AI-Key":"test-secret"})


def test_selected_sources_and_editable_geometry_survive_provider_boundary(monkeypatch):
    sent=provider(monkeypatch,DRAFT)
    r=post();assert r.status_code==200
    result=r.json();p=result['proposals'][0]
    prompt=json.loads(sent[0]['input'][0]['content'][0]['text'])
    assert prompt['online_source_metadata']==[SOURCE]
    assert 'design_basis' in sent[0]['instructions']
    assert p['design']['template']=='cone'
    assert p['design']['height_m']==16
    assert p['source_indices']==[1]
    assert p['dimensions_estimated'] is True
    assert result['reference_count']==1
    spec={**p['design'],'name':'灯台','scale':100,'style':p['style']}
    model=client.post('/api/model',json=spec)
    assert model.status_code==200
    assert model.json()['template']=='cone'
    assert model.json()['size_mm']['wall_height']==160
    assert client.post('/api/template.svg',json=spec).status_code==200


@pytest.mark.parametrize('draft',[
    None,{}, {**DRAFT,'height_m':-1},{**DRAFT,'height_m':float('inf')},
    {**DRAFT,'template':'arbitrary_mesh'},{**DRAFT,'width_m':1000},
    {**DRAFT,'template':'building','roof':'gable','pitch_deg':0},
    {**DRAFT,'scale':1},{**DRAFT,'api_key':'secret'},
])
def test_invalid_ai_geometry_is_not_applied_but_text_remains(monkeypatch,draft):
    provider(monkeypatch,draft)
    r=post();assert r.status_code==200
    assert r.json()['proposals'][0]['title']=='灯室を強調した灯台'
    assert r.json()['proposals'][0]['design'] is None


def test_offline_explicitly_does_not_claim_to_interpret_references():
    r=client.post('/api/proposals',json={"place":"海辺の灯台","sources":[SOURCE]})
    assert r.json()['provider']=='offline'
    assert '設計寸法の生成は行っていません' in ' '.join(r.json()['notes'])
    assert not any(p.get('design') for p in r.json()['proposals'])
