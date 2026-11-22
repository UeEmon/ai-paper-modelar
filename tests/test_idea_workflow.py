import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import idea_workflow as workflow

c=TestClient(app)


def test_genre_and_word_discover_drawings_photos_and_public_models_without_generation(monkeypatch):
    calls=[]
    async def images(q):
        calls.append(q);return [{'id':'a'*32,'title':q,'source_url':'https://commons.wikimedia.org/wiki/File:Drawing.jpg'}]
    async def models(q,offset):
        calls.append(('models',q,offset));return {'models':[{'id':'wooden_table','name':'Wooden Table'}]}
    monkeypatch.setattr(workflow,'search_images',images);monkeypatch.setattr(workflow,'public_search',models)
    r=c.get('/api/idea/references',params={'word':'lighthouse','genre':'architecture'})
    assert r.status_code==200
    d=r.json();assert d['diagrams'][0]['reference_type']=='diagram' and d['photos'][0]['reference_type']=='photo'
    assert 'elevation' in calls[0] and 'lighthouse' in calls[0] and calls[1]=='lighthouse'
    assert calls[2]==('models','lighthouse',0) and d['public_models'][0]['id']=='wooden_table'
    assert d['genre']=='architecture' and not d['warnings']


def test_drawing_only_vehicle_flow_and_partial_search_failures_are_explained(monkeypatch):
    calls=[]
    async def images(q):calls.append(q);raise ValueError('private-provider-error')
    async def models(q,offset):return {'models':[{'id':'car','name':'Car'}]}
    monkeypatch.setattr(workflow,'search_images',images);monkeypatch.setattr(workflow,'public_search',models)
    r=c.get('/api/idea/references',params={'word':'bus','genre':'vehicle','kind':'diagram'})
    d=r.json();assert len(calls)==1 and 'blueprint' in calls[0]
    assert d['photos']==[] and d['public_models'] and d['warnings']
    assert 'private-provider-error' not in r.text


@pytest.mark.parametrize('params',[{'word':'','genre':'architecture'},{'word':'model','genre':'unknown'},{'word':'model','kind':'invalid'}])
def test_invalid_idea_context_is_rejected_without_network(monkeypatch,params):
    async def forbidden(*args):pytest.fail('Unexpected network')
    monkeypatch.setattr(workflow,'search_images',forbidden);monkeypatch.setattr(workflow,'public_search',forbidden)
    assert c.get('/api/idea/references',params=params).status_code==422
