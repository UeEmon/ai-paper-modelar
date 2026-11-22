from io import BytesIO
import xml.etree.ElementTree as ET
import pytest
from pypdf import PdfReader
from app.generator import ModelSpec, miniature_mm, page_jobs, render_pdf, render_svg, summary

def test_scale():
    assert miniature_mm(15,150)==100
    spec=ModelSpec(scale=150,width_m=18,depth_m=8,height_m=7.5)
    dims=summary(spec)["size_mm"]
    assert dims["width"]==120
    assert dims["depth"]==53.3
    assert dims["total_height"]>dims["wall_height"]

def test_svg_valid():
    spec=ModelSpec(name="Model & <Station>")
    content=render_svg(spec)
    doc=ET.fromstring(content)
    assert doc.attrib["viewBox"]=="0 0 210 297"
    assert "Model &amp; &lt;Station&gt;" in content
    assert "50 mm CHECK" in content

def test_pdf_page_count():
    spec=ModelSpec(name="Test",scale=150,width_m=18,depth_m=8)
    data=render_pdf(spec)
    assert data.startswith(b"%PDF-")
    assert len(PdfReader(BytesIO(data)).pages)==len(page_jobs(spec))

def test_tiling():
    spec=ModelSpec(width_m=90,depth_m=25,scale=150)
    assert summary(spec)["pages"]>len(summary(ModelSpec())["parts"])

def test_gable_pitch_requires_slope():
    with pytest.raises(ValueError):
        ModelSpec(roof="gable",pitch_deg=0)


def test_gable_triangles_match_roof_slope():
    from math import cos, hypot, radians
    from app.generator import build_parts, miniature_mm
    spec = ModelSpec(width_m=18, depth_m=9, height_m=6, overhang_m=0, roof="gable", pitch_deg=30)
    parts = {p["name"]: p for p in build_parts(spec)}
    d = miniature_mm(spec.depth_m, spec.scale)
    w = miniature_mm(spec.width_m, spec.scale)
    # Gables are on the depth walls; the long walls are plain rectangles.
    assert parts["Left wall"]["graphics"][0]["type"] == "poly"
    assert parts["Front wall"]["graphics"][0]["type"] == "rect"
    pts = parts["Left wall"]["graphics"][0]["points"]
    rake = hypot(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    assert abs(rake - (d / 2) / cos(radians(30))) < 1e-6
    assert abs(parts["Roof A"]["w"] - 10 - w) < 1e-6


def test_general_papercraft_box_template_and_real_scale():
    from app.generator import build_parts
    spec = ModelSpec(
        name="Handmade prop",
        subject_type="prop",
        template="box",
        input_unit="cm",
        scale=1,
        width_m=0.08,
        depth_m=0.04,
        height_m=0.06,
        roof="flat",
        pitch_deg=0,
    )
    parts = build_parts(spec)
    assert len(parts) == 6
    assert [p["name"] for p in parts][-2:] == ["Top face", "Bottom face"]
    assert all("window" not in p["name"].lower() for p in parts)
    dimensions = summary(spec)
    assert dimensions["size_mm"]["width"] == 80
    assert dimensions["size_mm"]["total_height"] == 60
    assert dimensions["subject_type"] == "prop"
    assert dimensions["template"] == "box"
    assert render_pdf(spec).startswith(b"%PDF-")
    assert "<svg" in render_svg(spec)


def test_legacy_model_defaults_unchanged():
    spec = ModelSpec(name="Railway depot", scale=150)
    assert spec.subject_type == "architecture"
    assert spec.template == "building"
    assert spec.input_unit == "m"
    assert any(part["name"] == "Roof A" for part in __import__(
        "app.generator", fromlist=["build_parts"]
    ).build_parts(spec))


def test_generic_categories_and_custom_scales():
    for subject in ["architecture","vehicle","landscape","prop",
                    "character","original","railway","other"]:
        spec = ModelSpec(subject_type=subject, template="box", scale=12)
        assert summary(spec)["subject_type"] == subject
