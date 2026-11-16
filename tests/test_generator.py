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
