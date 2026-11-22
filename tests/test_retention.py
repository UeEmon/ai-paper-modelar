from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app import projects, retention


def test_sources_never_written_and_outputs_survive_restart(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_MODELAR_DATA_DIR',str(tmp_path))
    raw=BytesIO();Image.new('RGB',(100,100),'red').save(raw,format='PNG')
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'private-source-name'}).json()['id']
        a=c.post(f'/api/projects/{pid}/assets',files={'file':('secret.png',raw.getvalue(),'image/png')}).json()
        assert c.get(a['original_url']).content==raw.getvalue()
        assert list(tmp_path.rglob('*'))==[]
        spec={'name':'Finished','scale':150,'width_m':18,'depth_m':8,'height_m':7.5}
        rendered=c.post('/api/template.pdf',json=spec)
        assert rendered.status_code==200
        saved=c.get('/api/outputs').json()['outputs']
        assert len(saved)==1 and saved[0]['id'].endswith('.pdf')
    with TestClient(app) as c:
        assert c.get('/api/projects').json()['projects']==[]
        assert c.get(a['original_url']).status_code==404
        assert c.get(saved[0]['url']).content==rendered.content
        assert c.delete(saved[0]['url']).status_code==204
        assert c.get('/api/outputs').json()['outputs']==[]


def test_migration_removes_only_old_app_sources(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_MODELAR_DATA_DIR',str(tmp_path))
    (tmp_path/'projects'/'old'/'files').mkdir(parents=True)
    (tmp_path/'projects'/'old'/'files'/'reference.png').write_bytes(b'secret')
    for name in ['library.sqlite3','library.sqlite3-wal','library.sqlite3-shm','library.sqlite3-journal']:(tmp_path/name).write_bytes(b'secret')
    result=retention.save_output(b'<svg/>','svg')
    retention.purge_legacy_sources()
    assert [p.name for p in tmp_path.iterdir()]==['outputs']
    assert (tmp_path/'outputs'/result).read_bytes()==b'<svg/>'


def test_expired_work_is_actually_released_without_a_new_request(monkeypatch):
    p=projects.create_project(projects.ProjectCreate(name='temporary'))
    future=projects._projects[p['id']]['_touched']+901
    monkeypatch.setattr(projects.time,'time',lambda:future)
    retention.prune_temporary()
    assert p['id'] not in projects._projects


def test_large_uploads_stay_memory_only_and_are_bounded():
    assert retention.MultiPartParser.spool_max_size>retention.MAX_BODY
    c=TestClient(app)
    assert c.post('/api/uploads',content=b'x'*(retention.MAX_BODY+1)).status_code==413
    assert c.get('/api/outputs/'+'g'*64+'.pdf').status_code==404
