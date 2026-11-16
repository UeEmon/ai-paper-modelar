import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
SVG = re.compile(r"^\s*(<\?xml[^>]*>\s*)?<svg[\s>]", re.I)
KINDS = ["tunnel", "bridge", "viaduct", "station", "platform", "building", "landmark", "mountain", "water", "other"]


def body(**obj):
    o = {"name": "テスト", "kind": "tunnel", "length": 248, "width": 60, "height": 40, "note": ""}
    o.update(obj)
    return {"source": "senrolab", "scale": "1/150", "paper": "A4", "object": o,
            "notice": "SenroLab のシミュレーション上の仮オブジェクトです。"}


def test_health():
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_returns_svg_pages(kind):
    res = client.post("/v1/nets", json=body(kind=kind, height=20))
    assert res.status_code == 200, res.text
    data = res.json()
    assert 1 <= len(data["pages"]) <= 20
    for page in data["pages"]:
        assert SVG.match(page)
        assert 'width="210mm"' in page and 'height="297mm"' in page
        assert "<script" not in page and "href=" not in page
        assert "仮オブジェクト" in page
    assert len(data.get("warnings", [])) <= 20


def test_a3_uses_a3_size():
    page = client.post("/v1/nets", json={**body(), "paper": "A3"}).json()["pages"][0]
    assert 'width="297mm"' in page and 'height="420mm"' in page


def test_tunnel_is_raised_to_train_height():
    data = client.post("/v1/nets", json=body(height=20)).json()
    assert any("30mm" in w for w in data["warnings"])


def test_small_station_uses_gable_roof_generator():
    data = client.post("/v1/nets", json=body(kind="station", length=80, width=40, height=25)).json()
    assert any("切妻" in w for w in data["warnings"])
    assert "屋根A" in "".join(data["pages"]) and len(data["pages"]) == 1


def test_large_building_falls_back_to_box():
    data = client.post("/v1/nets", json=body(kind="building", length=600, width=150, height=60)).json()
    assert any("箱形" in w for w in data["warnings"])


def test_name_is_escaped():
    page = client.post("/v1/nets", json=body(name="<b>&")).json()["pages"][0]
    assert "<b>&" not in page and "&lt;b&gt;&amp;" in page


def test_invalid_input_is_400_with_message():
    res = client.post("/v1/nets", json=body(kind="castle"))
    assert res.status_code == 400
    assert res.json() == {"error": "入力が正しくありません"}
    assert client.post("/v1/nets", json={**body(), "extra": 1}).status_code == 400


def test_too_large_is_422():
    res = client.post("/v1/nets", json=body(kind="water", length=2000, width=800, height=0))
    assert res.status_code in (200, 422)
    huge = client.post("/v1/nets", json=body(kind="building", length=2000, width=800, height=400))
    assert huge.status_code == 422 and "20枚" in huge.json()["error"]


def test_token(monkeypatch):
    monkeypatch.setenv("PAPERCRAFT_API_TOKEN", "s" * 40)
    assert client.post("/v1/nets", json=body()).status_code == 401
    wrong = client.post("/v1/nets", json=body(), headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401 and "error" in wrong.json()
    ok = client.post("/v1/nets", json=body(), headers={"Authorization": "Bearer " + "s" * 40})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200


def test_existing_api_errors_unchanged():
    res = client.post("/api/model", json={"scale": 1})
    assert res.status_code == 422 and "detail" in res.json()
