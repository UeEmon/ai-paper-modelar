from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_home():
    assert client.get("/").status_code==200
    assert client.get("/api/health").json()=={"status":"ok"}

def test_offline_proposals(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER","none")
    r=client.post("/api/proposals",json={"place":"旧国立駅舎","style":"anime","scale":150})
    assert r.status_code==200
    assert r.json()["provider"]=="offline"
    assert len(r.json()["proposals"])==3

def test_template_endpoints():
    model={"name":"Sample","scale":150,"width_m":18,"depth_m":8,"height_m":7.5}
    info=client.post("/api/model",json=model)
    assert info.status_code==200
    svg=client.post("/api/template.svg?page=0",json=model)
    pdf=client.post("/api/template.pdf",json=model)
    assert svg.status_code==200 and svg.text.startswith("<?xml")
    assert pdf.status_code==200 and pdf.content.startswith(b"%PDF-")

def test_invalid_scale():
    assert client.post("/api/model",json={"scale":0}).status_code==422


def test_general_topic_offline_ai_and_model_request(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "none")
    prompt = client.post("/api/proposals", json={
        "place": "蒸気機関車ではない架空の飛行船",
        "subject_type": "vehicle", "style": "anime", "scale": 24
    })
    assert prompt.status_code == 200
    assert prompt.json()["provider"] == "offline"
    layout = client.post("/api/model", json={
        "name": "箱型のオリジナル小物",
        "subject_type": "original", "template": "box",
        "input_unit": "mm", "width_m": 0.08, "depth_m": 0.04,
        "height_m": 0.05, "scale": 1, "roof": "flat", "pitch_deg": 0
    })
    assert layout.status_code == 200, layout.text
    assert layout.json()["size_mm"]["width"] == 80
    assert layout.json()["template"] == "box"
