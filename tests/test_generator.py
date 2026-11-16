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
