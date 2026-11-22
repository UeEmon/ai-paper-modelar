import httpx
import pytest
from fastapi.testclient import TestClient
from app import research as module
from app.main import app

client=TestClient(app)
HTTP_CLIENT=httpx.AsyncClient
RSS=b'''<?xml version="1.0"?><rss version="2.0"><channel><item><title>Lighthouse official</title><link>https://lighthouse.example.org/guide#section</link><description>&lt;b&gt;Circular tower&lt;/b&gt; with a lamp.</description></item><item><title>Duplicate</title><link>https://lighthouse.example.org/guide</link><description>Same page.</description></item><item><title>Private</title><link>http://127.0.0.1/secret</link></item></channel></rss>'''
WIKI={'query':{'pages':{'1':{'title':'Lighthouse','index':1,'fullurl':'https://ja.wikipedia.org/wiki/Lighthouse','extract':'A tower with a light.'}}}}


def mock(monkeypatch,web=RSS,wiki=WIKI,web_status=200,wiki_status=200):
    original=HTTP_CLIENT;sent=[]
    def handler(request):
        sent.append(request)
        if request.url.host=='www.bing.com':return httpx.Response(web_status,content=web)
        assert request.url.host=='ja.wikipedia.org', 'Result pages must never be fetched'
        return httpx.Response(wiki_status,json=wiki)
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    return sent


def test_broad_search_merges_public_web_with_encyclopedia_and_deduplicates(monkeypatch):
    sent=mock(monkeypatch)
    r=client.get('/api/research',params={'q':'Lighthouse'})
    assert r.status_code==200
    data=r.json();assert data['scope']=='all'
    assert {p['id'] for p in data['providers']}=={'web','wikipedia'}
    assert len(sent)==2 and all(req.method=='GET' for req in sent)
    assert {req.url.params['q'] for req in sent if req.url.host=='www.bing.com'}=={'Lighthouse'}
    assert len(data['results'])==2
    web=data['results'][0]
    assert web['url']=='https://lighthouse.example.org/guide'
    assert web['summary']=='Circular tower with a lamp.'
    assert web['provider']=='web' and web['domain']=='lighthouse.example.org'
    assert web['query_match'] is True
    assert web['dimensions_verified'] is False and web['reuse_rights_verified'] is False


@pytest.mark.parametrize('scope,host',[('web','www.bing.com'),('wikipedia','ja.wikipedia.org')])
def test_requested_scope_only_contacts_that_provider(monkeypatch,scope,host):
    sent=mock(monkeypatch)
    r=client.get('/api/research',params={'q':'Lighthouse','scope':scope})
    assert r.status_code==200 and len(sent)==1 and sent[0].url.host==host
    assert {x['provider'] for x in r.json()['results']}=={scope}


def test_one_provider_failure_keeps_other_results_with_explicit_warning(monkeypatch):
    mock(monkeypatch,web_status=503)
    r=client.get('/api/research',params={'q':'Lighthouse'})
    assert r.status_code==200
    assert r.json()['results'][0]['provider']=='wikipedia'
    assert 'Web検索' in ' '.join(r.json()['warnings'])
    mock(monkeypatch,web_status=503,wiki_status=503)
    assert client.get('/api/research',params={'q':'Lighthouse'}).status_code==503


@pytest.mark.parametrize('payload',[b'<html>not a feed</html>',b'<rss><channel>',b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss><channel>&secret;</channel></rss>',b'x'*(module.MAX_RESPONSE_BYTES+1)])
def test_bad_xml_entities_and_oversize_responses_are_rejected_without_fetching_links(monkeypatch,payload):
    sent=mock(monkeypatch,web=payload)
    r=client.get('/api/research',params={'q':'Lighthouse'})
    assert r.status_code==200
    assert r.json()['results'][0]['provider']=='wikipedia'
    assert any(p['status']=='error' for p in r.json()['providers'])
    assert len(sent)==2


@pytest.mark.parametrize('url',['javascript:alert(1)','file:///etc/passwd','https://user:secret@example.org/page','http://localhost/x','http://service.local/x','http://10.0.0.1/x','http://169.254.169.254/latest/meta-data','http://[::1]/x','https://example.org:99999/','https://example.org/path\nheader','https://example.org:0/'])
def test_reference_urls_exclude_nonweb_and_private_destinations(url):
    assert module.public_url(url) is None


def test_exact_topic_matches_precede_unrelated_web_results(monkeypatch):
    rss=RSS.replace(b'Lighthouse official',b'Unrelated dictionary')
    mock(monkeypatch,web=rss)
    r=client.get('/api/research',params={'q':'Lighthouse'})
    data=r.json()['results']
    assert data[0]['title']=='Lighthouse' and data[0]['query_match'] is True
    assert data[-1]['query_match'] is False


def test_empty_results_and_invalid_scopes(monkeypatch):
    mock(monkeypatch,web=b'<rss><channel/></rss>',wiki={})
    r=client.get('/api/research',params={'q':'No results'})
    assert r.status_code==200 and r.json()['results']==[]
    assert client.get('/api/research',params={'q':'No results','scope':'untrusted'}).status_code==422
