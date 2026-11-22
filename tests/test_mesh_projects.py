"""Temporary OBJ/STL work-session integration."""
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.projects import LibraryProblem, get_asset_for_ai

client = TestClient(app)

TETRA = b"""v 0 0 0
v 10 0 0
v 0 10 0
v 0 0 10
f 1 3 2
f 1 2 4
f 2 3 4
f 3 1 4
"""


@pytest.fixture(autouse=True)
def temp_root(tmp_path,monkeypatch):
    monkeypatch.setenv("PAPER_MODELAR_DATA_DIR",str(tmp_path/"model-storage"))


def test_project_stores_mesh_original_and_thumbnail_and_copy():
    a=client.post("/api/projects",json={"name":"3D模型A"}).json()["id"]
    b=client.post("/api/projects",json={"name":"3D模型B"}).json()["id"]
    response=client.post("/api/projects/"+a+"/assets",
        data={"view":"other","notes":"OBJ coordinates in mm"},
        files={"file":("small.obj",TETRA,"application/octet-stream")})
    assert response.status_code==201,response.text
    item=response.json()
    assert item["kind"]=="mesh"
    assert item["name"]=="small.obj"
    assert client.get(item["original_url"]).content==TETRA
    preview=client.get(item["preview_url"])
    assert preview.status_code==200
    assert preview.content.startswith(b"\xff\xd8")
    with pytest.raises(LibraryProblem,match="画像AI"):
        get_asset_for_ai(a,item["id"])
    stored=client.get("/api/projects/"+a).json()
    assert len(stored["assets"])==1
    copied=client.post("/api/projects/"+a+"/assets/"+item["id"]+"/copy",
        json={"target_project_id":b})
    assert copied.status_code==201,copied.text
    second=copied.json()
    assert second["id"]!=item["id"]
    assert client.get(second["original_url"]).content==TETRA
    assert client.delete("/api/projects/"+a+"/assets/"+item["id"]).status_code==204
    assert client.get(item["original_url"]).status_code==404
    assert client.get(second["original_url"]).status_code==200


def test_invalid_mesh_cannot_be_saved():
    pid=client.post("/api/projects",json={"name":"reject"}).json()["id"]
    response=client.post("/api/projects/"+pid+"/assets",
        files={"file":("bad.obj",b"v 0 0 0\n","application/octet-stream")})
    assert response.status_code==422
    response=client.post("/api/projects/"+pid+"/assets",
        files={"file":("huge.stl",b"x"*(5*1024*1024+1),"application/octet-stream")})
    assert response.status_code==413
