import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.generated_models import save_model
from app.image_geometry import Scene,Component,build_model


def result():
    return build_model(Scene(components=[Component(shape='box',size=(30,40,20),position=(0,0,0),color='#ccaa88')]),100)


def test_generated_models_survive_restart_and_support_download_preview_delete():
    model=result()
    with TestClient(app) as c:
        saved=save_model({**model,'source':{'image':'secret-reference'},'api_key':'secret-key','notes':['private-prompt']},name='生成した家',provider='ollama')
        assert c.get('/api/generated-models').json()['models'][0]['id']==saved['id']
    with TestClient(app) as c:
        restored=c.get(saved['preview_url']);assert restored.status_code==200
        assert restored.json()['name']=='生成した家' and len(restored.json()['faces'])==12
        assert c.get(saved['obj_url']).content==model['obj'].encode()
        assert c.get('/api/generated-models/'+saved['id']+'/original.glb').status_code==404
        assert 'secret-reference' not in restored.text and 'private-prompt' not in restored.text
        assert c.delete(saved['preview_url']).status_code==204
        assert c.get(saved['obj_url']).status_code==404
        assert c.get('/api/generated-models').json()['models']==[]


def test_only_output_geometry_and_whitelisted_metadata_are_persisted(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_MODELAR_DATA_DIR',str(tmp_path))
    save_model({**result(),'source':{'image':'private-image'},'prompt':'private-prompt','api_key':'private-key'},name='Generated',provider='openai')
    files=[p for p in tmp_path.rglob('*') if p.is_file()]
    assert {p.name for p in files}=={'model.obj','metadata.json'}
    for p in files:
        for secret in ['private-image','private-prompt','private-key']:assert secret not in p.read_text()
    meta=json.loads(next(p for p in files if p.name=='metadata.json').read_text())
    assert set(meta)=={'id','name','provider','created_at','size_mm','faces','colors','has_glb'}


def test_partial_save_failure_is_not_listed_and_leaves_no_model_files(monkeypatch):
    def fail(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(Path,'write_bytes',fail)
    with pytest.raises(HTTPException) as caught:save_model(result(),name='Generated',provider='ollama')
    assert caught.value.status_code==507
    assert TestClient(app).get('/api/generated-models').json()['models']==[]


def test_invalid_ids_and_symlinks_cannot_expose_other_files(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPER_MODELAR_DATA_DIR',str(tmp_path))
    folder=tmp_path/'models';folder.mkdir();target=tmp_path/'private';target.mkdir();(target/'model.obj').write_text('private')
    (folder/('a'*32)).symlink_to(target,target_is_directory=True)
    c=TestClient(app)
    assert c.get('/api/generated-models/'+('a'*32)+'/model.obj').status_code==404
    assert c.delete('/api/generated-models/'+('a'*32)).status_code==404
    assert c.get('/api/generated-models/not-an-id').status_code==404
    assert (target/'model.obj').read_text()=='private'
