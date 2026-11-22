"""RAM-only work-session integration tests."""
from io import BytesIO
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_MODELAR_DATA_DIR", str(tmp_path / "storage"))

def png_bytes():
    b=BytesIO()
    Image.new("RGB",(100,60),"white").save(b,format="PNG")
    return b.getvalue()

def new_project(name):
    r=client.post("/api/projects",json={"name":name,"model_spec":{"name":name,"scale":150}})
    assert r.status_code==201,r.text
    return r.json()["id"]

def test_work_sessions_edit_and_delete():
    pid=new_project("駅舎A")
    r=client.patch("/api/projects/"+pid,json={
        "name":"駅舎B","notes":"縮尺の確認済み",
        "model_spec":{"name":"駅舎B","scale":80,"width_m":12}
    })
    assert r.status_code==200,r.text
    # A second client in the same process can use the unexpired work session.
    x=TestClient(app).get("/api/projects/"+pid).json()
    assert x["project"]["name"]=="駅舎B"
    assert x["project"]["model_spec"]["scale"]==80
    assert client.get("/api/projects").json()["projects"][0]["id"]==pid
    assert client.delete("/api/projects/"+pid).status_code==204
    assert client.get("/api/projects/"+pid).status_code==404

def test_originals_copy_edit_delete_and_isolation():
    first=new_project("A")
    second=new_project("B")
    r=client.post("/api/projects/"+first+"/assets",
        data={"view":"front","notes":"撮影した写真"},
        files={"file":("front.png",png_bytes(),"image/png")})
    assert r.status_code==201,r.text
    src=r.json()
    assert client.get(src["original_url"]).content==png_bytes()
    assert client.get(src["preview_url"]).content.startswith(b"\xff\xd8")
    forbidden="/api/projects/"+second+"/assets/"+src["id"]+"/original"
    assert client.get(forbidden).status_code==404
    updated=client.patch("/api/projects/"+first+"/assets/"+src["id"],
        json={"name":"edited.png","notes":"反対側も撮る","view":"left"})
    assert updated.status_code==200
    copy=client.post("/api/projects/"+first+"/assets/"+src["id"]+"/copy",
        json={"target_project_id":second})
    assert copy.status_code==201,copy.text
    dest=copy.json()
    assert dest["id"]!=src["id"]
    assert dest["name"]=="edited.png"
    assert client.get(dest["original_url"]).content==png_bytes()
    assert client.delete("/api/projects/"+first+"/assets/"+src["id"]).status_code==204
    assert client.get(src["original_url"]).status_code==404
    assert client.get(dest["original_url"]).status_code==200
    assert client.delete("/api/projects/"+second).status_code==204
    assert client.get(dest["original_url"]).status_code==404

def test_invalid_files_and_project_ids():
    pid=new_project("Sample")
    r=client.post("/api/projects/"+pid+"/assets",
        files={"file":("bad.txt",b"bad","text/plain")})
    assert r.status_code==415
    r=client.post("/api/projects/"+pid+"/assets",
        files={"file":("oversize.png",b"a"*(15*1024*1024+1),"image/png")})
    assert r.status_code==413
    assert client.get("/api/projects/"+"z"*32).status_code==404

def test_no_external_media_without_consent(monkeypatch):
    import asyncio,json,httpx
    from app import ai
    from app.ai import ProposalRequest
    pid=new_project("Station")
    asset=client.post("/api/projects/"+pid+"/assets",
        files={"file":("f.png",png_bytes(),"image/png")}).json()
    sent=[]
    original=httpx.AsyncClient
    def handler(req):
        sent.append(json.loads(req.content))
        text=json.dumps({"proposals":[{"style":"faithful","title":"案","description":"説明"}],"notes":[]})
        return httpx.Response(200,json={"output":[{"content":[{"type":"output_text","text":text}]}]})
    monkeypatch.setattr(ai.httpx,"AsyncClient",
        lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    base={"place":"Old Station","project_id":pid,"project_asset_ids":[asset["id"]]}
    a=asyncio.run(ai.proposals(ProposalRequest(**base,include_uploads=False), ai.AICredentials("openai", "test-model", "fake")))
    assert a["analyzed_uploads"]==0
    assert "input_image" not in json.dumps(sent[-1])
    b=asyncio.run(ai.proposals(ProposalRequest(**base,include_uploads=True), ai.AICredentials("openai", "test-model", "fake")))
    assert b["analyzed_uploads"]==1
    assert "input_image" in json.dumps(sent[-1])


def test_generic_settings_remain_in_active_work_session():
    pid = new_project("Vintage bus")
    data = {
        "name": "Vintage bus",
        "model_spec": {
            "name": "Vintage bus", "scale": 24,
            "subject_type": "vehicle", "template": "box",
            "input_unit": "cm",
            "width_m": 0.21, "depth_m": 0.09, "height_m": 0.11,
            "roof": "flat", "pitch_deg": 0,
        },
    }
    response = client.patch("/api/projects/" + pid, json=data)
    assert response.status_code == 200, response.text
    reopened = client.get("/api/projects/" + pid).json()["project"]["model_spec"]
    assert reopened["subject_type"] == "vehicle"
    assert reopened["template"] == "box"
    assert reopened["input_unit"] == "cm"
    assert reopened["width_m"] == 0.21
    assert reopened["scale"] == 24
