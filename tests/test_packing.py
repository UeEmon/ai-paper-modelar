"""A4 packing, cut/fold metadata, vector export and pagination guard tests."""
from io import BytesIO
import xml.etree.ElementTree as ET

import pytest
from pypdf import PdfReader

from app.generator import (
    AREA_X, AREA_Y, AREA_W, AREA_H,
    ModelSpec, build_parts, page_jobs, render_pdf, render_svg
)


def small_box():
    return ModelSpec(name="Miniature object", template="box", scale=1,
                     width_m=0.060, depth_m=0.040, height_m=0.050,
                     roof="flat", pitch_deg=0)


def test_small_parts_pack_on_one_a4():
    spec = small_box()
    parts = build_parts(spec)
    pages = page_jobs(spec)
    assert len(parts) == 6
    assert len(pages) == 1
    assert len(pages[0]["placements"]) == 6
    assert len(PdfReader(BytesIO(render_pdf(spec))).pages) == 1


def test_packed_parts_never_overlap_and_remain_in_printable_area():
    for spec in (
        small_box(),
        ModelSpec(name="Sample", template="building", scale=150),
        ModelSpec(name="Cylinder", template="cylinder", scale=1,
                  width_m=0.04, height_m=0.07),
    ):
        for page in page_jobs(spec):
            rectangles = []
            for item in page["placements"]:
                x, y = item["dst_x"], item["dst_y"]
                w, h = item["clip_w"], item["clip_h"]
                assert x >= AREA_X - 1e-6 and y >= AREA_Y - 1e-6
                assert x + w <= AREA_X + AREA_W + 1e-6
                assert y + h <= AREA_Y + AREA_H + 1e-6
                for x2, y2, w2, h2 in rectangles:
                    assert x + w <= x2 or x2 + w2 <= x or y + h <= y2 or y2 + h2 <= y
                rectangles.append((x, y, w, h))


def test_svg_contains_distinct_cut_and_fold_graphics():
    spec = ModelSpec(template="prism", sides=5, scale=1,
                     width_m=0.040, height_m=0.06)
    svg = render_svg(spec)
    root = ET.fromstring(svg)
    assert root.attrib["width"] == "210mm"
    assert 'data-layer="cut"' in svg
    assert 'data-layer="fold"' in svg
    assert "50 mm CHECK" in svg
    assert "Prism side" in svg


def test_large_part_uses_tiled_pages_and_guard():
    big = ModelSpec(template="box", scale=1,
                    width_m=0.600, depth_m=0.10, height_m=0.11,
                    roof="flat", pitch_deg=0)
    pages = page_jobs(big)
    assert len(pages) >= 4
    assert any(p["tile"][2] > 1 for page in pages for p in page["placements"])
    for i in range(len(pages)):
        assert "<svg" in render_svg(big, i)
    huge = ModelSpec(template="cylinder", scale=1,
                     width_m=100, height_m=50)
    with pytest.raises(ValueError, match="over 100"):
        page_jobs(huge)
