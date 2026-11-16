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
