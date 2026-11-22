"""Parametric unfolding geometry, exact dimensions and export regression tests."""
from io import BytesIO
from math import cos, hypot, isfinite, pi, sin
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from app.generator import ModelSpec, build_parts, page_jobs, render_pdf, render_svg, summary
from app.net_engine import _frustum_side, _strip, build_parametric_parts


def spec_for(shape, **kwargs):
    params = {
        "name": "Unit test model",
        "template": shape,
        "subject_type": "prop",
        "scale": 1,
        "width_m": 0.05,
        "depth_m": 0.05,
        "height_m": 0.06,
        "roof": "flat",
        "pitch_deg": 0,
        "sides": 6,
        "top_ratio": 0.4,
    }
    params.update(kwargs)
    return ModelSpec(**params)


@pytest.mark.parametrize("shape,expected_parts", [
    ("cylinder", 3), ("cone", 3), ("prism", 3),
    ("pyramid", 7), ("building", 5), ("box", 6),
])
def test_templates_export_svg_and_pdf(shape, expected_parts):
    spec = spec_for(shape)
    parts = build_parts(spec)
    assert len(parts) == expected_parts
    assert summary(spec)["template"] == shape
    assert len(PdfReader(BytesIO(render_pdf(spec))).pages) == len(page_jobs(spec))
    for i in range(len(page_jobs(spec))):
        page = ET.fromstring(render_svg(spec, i))
        assert page.attrib["width"] == "210mm"
        assert page.attrib["height"] == "297mm"


@pytest.mark.parametrize("shape", ["cylinder", "cone", "prism", "pyramid"])
def test_geometric_parts_have_bounded_points_and_folds(shape):
    spec = spec_for(shape)
    parts = build_parts(spec)
    assert len(parts) <= 13
    for part in parts:
        assert part["w"] > 0
        assert part["h"] > 0
        for graphic in part["graphics"]:
            assert graphic["kind"] in ("cut", "fold", "detail")
            if graphic["type"] == "poly":
                pts = graphic["points"]
            elif graphic["type"] == "line":
                pts = [(graphic["x1"], graphic["y1"]),
                       (graphic["x2"], graphic["y2"])]
            else:
                pts = [(graphic["x"], graphic["y"]),
                       (graphic["x"] + graphic["w"], graphic["y"] + graphic["h"])]
            assert all(isfinite(x) and isfinite(y) for x, y in pts)
            assert all(-1e-5 <= x <= part["w"] + 1e-5 and
                       -1e-5 <= y <= part["h"] + 1e-5 for x, y in pts)


def test_cylinder_wrap_length_matches_circumference():
    radius = 25.0
    spec = spec_for("cylinder")
    strip, top, bottom = build_parts(spec)
    seam_length = min(5.0, 60.0 * 0.22)
    assert abs(strip["w"] - (2 * pi * radius + seam_length + 12)) < 1e-5
    assert abs(top["w"] - 62.0) < 0.1
    assert top["w"] == bottom["w"]
    # Body outline is single cut contour. Creases are independently scored.
    assert sum(g["kind"] == "cut" for g in strip["graphics"]) == 1
    assert sum(g["kind"] == "fold" for g in strip["graphics"]) >= 3


def test_frustum_arc_lengths_and_top_cap():
    bottom_radius = 25.0
    upper_radius = 10.0
    height = 60.0
    side = _frustum_side(bottom_radius, upper_radius, height, "#e6e6e6")
    pts = side["graphics"][0]["points"]
    count = max(32, min(512, __import__("math").ceil(2 * pi * bottom_radius / 1.5)))
    outer_arc_length = sum(hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
                           for i in range(count))
    inner = pts[count + 1:count + 1 + count + 1]
    inner_arc_length = sum(hypot(inner[i+1][0]-inner[i][0],
                                 inner[i+1][1]-inner[i][1])
                           for i in range(count))
    assert abs(outer_arc_length - 2 * pi * bottom_radius) < 0.1
    assert abs(inner_arc_length - 2 * pi * upper_radius) < 0.1
    assert any(g["kind"] == "fold" for g in side["graphics"])


def test_cone_pointed_and_zero_taper_cylinder():
    pointed = build_parts(spec_for("cone", top_ratio=0))
    assert len(pointed) == 2
    assert pointed[1]["name"] == "Bottom cap"
    straight = build_parts(spec_for("cone", top_ratio=1))
    assert len(straight) == 3
    assert straight[0]["name"] == "Cylinder side"


def test_prism_side_length_fold_count():
    for sides in (3, 5, 8, 12):
        spec = spec_for("prism", sides=sides)
        strip, top, bottom = build_parts(spec)
        theoretical_side = 50 * sin(pi / sides)
        assert abs(strip["w"] - (sides * theoretical_side + 17)) < 0.01
        creases = [g for g in strip["graphics"] if g["kind"] == "fold"]
        assert len(creases) >= 2 * sides + sides - 1
        assert top["w"] == bottom["w"]


def test_pyramid_has_one_base_and_n_faces():
    spec = spec_for("pyramid", sides=9)
    parts = build_parts(spec)
    assert len(parts) == 10
    assert sum(p["name"].startswith("Triangle") for p in parts) == 9
    assert parts[0]["name"] == "Base polygon"


def test_overly_large_templates_rejected_before_page_allocation():
    spec = spec_for("cylinder", width_m=100, height_m=50)
    with pytest.raises(ValueError, match="over 100"):
        page_jobs(spec)


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValidationError):
        spec_for("prism", sides=2)
    with pytest.raises(ValidationError):
        spec_for("prism", sides=13)
    with pytest.raises(ValidationError):
        spec_for("cone", top_ratio=1.4)


def test_legacy_building_and_box_unchanged():
    building = spec_for("building", scale=150, width_m=18, depth_m=8, roof="gable", pitch_deg=30)
    assert any(part["name"] == "Roof A" for part in build_parts(building))
    box = spec_for("box")
    assert len(build_parts(box)) == 6
