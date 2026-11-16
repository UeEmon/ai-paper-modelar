"""Upload endpoint coverage: images, PDFs, rejects and AI consent defaults."""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen import canvas

from app.main import app
from app.ai import ProposalRequest


client = TestClient(app)


def image_bytes(fmt="PNG"):
    stream = BytesIO()
    Image.new("RGB", (200, 120), "#d5b69a").save(stream, format=fmt)
    return stream.getvalue()


def pdf_bytes():
    stream = BytesIO()
    c = canvas.Canvas(stream)
    c.drawString(72, 700, "Measured plan is a user reference, not verified")
    c.showPage()
    c.save()
    return stream.getvalue()


def test_png_upload_preview_and_delete():
    response = client.post(
        "/api/uploads",
        data={"view": "front", "notes": "正面図"},
        files={"file": ("front.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["kind"] == "image"
    assert info["view"] == "front"
    assert info["notes"] == "正面図"
    asset_id = info["id"]
    assert len(asset_id) == 32
    preview = client.get(info["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content.startswith(b"\xff\xd8")
    assert client.get("/api/uploads/" + asset_id).json()["name"] == "front.png"
    assert client.delete("/api/uploads/" + asset_id).status_code == 204
    assert client.get(info["preview_url"]).status_code == 404


def test_pdf_preview_and_extract_text():
    response = client.post(
        "/api/uploads",
        data={"view": "plan", "notes": "平面図"},
        files={"file": ("plan.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["kind"] == "pdf"
    assert info["has_text"] is True
    assert client.get(info["preview_url"]).content.startswith(b"\xff\xd8")
    assert client.delete("/api/uploads/" + info["id"]).status_code == 204


def test_invalid_and_oversized_files():
    invalid = client.post(
        "/api/uploads",
        files={"file": ("fake.svg", b"<svg></svg>", "image/svg+xml")},
    )
    assert invalid.status_code == 415
    fake_pdf = client.post(
        "/api/uploads",
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )
    assert fake_pdf.status_code == 415
    too_big = client.post(
        "/api/uploads",
        files={"file": ("huge.jpg", b"Z" * (15 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert too_big.status_code == 413


def test_ai_opt_in_and_legacy_proposal():
    assert ProposalRequest(place="門司港駅").include_uploads is False
    result = client.post("/api/proposals", json={"place": "門司港駅"})
    assert result.status_code == 200


def test_uploaded_media_requires_explicit_ai_consent(monkeypatch):
    """Only checked opt-in may include base64 media in provider requests."""
    import asyncio
    import json
    import httpx
    from app import ai
    from app.uploads import add_asset, delete_asset

    asset = add_asset(image_bytes(), "station.png", "front", "駅正面")
    sent = []
    original_client = httpx.AsyncClient

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        proposal = json.dumps({
            "proposals": [{"style": "faithful", "title": "再現型",
                           "description": "外観を確認して制作"}],
            "notes": ["寸法は未確認"]
        }, ensure_ascii=False)
        return httpx.Response(
            200, json={"output": [{"content": [
                {"type": "output_text", "text": proposal}
            ]}]},
        )

    def fake_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai.httpx, "AsyncClient", fake_client)
    try:
        no_consent = ai.ProposalRequest(
            place="旧駅舎", upload_ids=[asset.id], include_uploads=False
        )
        result = asyncio.run(ai.proposals(no_consent))
        assert result["analyzed_uploads"] == 0
        assert "input_image" not in json.dumps(sent[-1])

        consent = ai.ProposalRequest(
            place="旧駅舎", upload_ids=[asset.id], include_uploads=True
        )
        result = asyncio.run(ai.proposals(consent))
        assert result["analyzed_uploads"] == 1
        assert "input_image" in json.dumps(sent[-1])
        assert "station.png" in json.dumps(sent[-1])
    finally:
        delete_asset(asset.id)
