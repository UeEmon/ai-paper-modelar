"""Dimension-safe A4 vector papercraft layouts (all coordinates are millimetres)."""
from __future__ import annotations

from io import BytesIO
from math import ceil, cos, radians, tan
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field, model_validator
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = 210.0, 297.0
AREA_X, AREA_Y, AREA_W, AREA_H, OVERLAP = 12.0, 28.0, 186.0, 225.0, 5.0

Style = Literal["faithful", "standard", "anime", "retro", "easy"]
Roof = Literal["gable", "flat"]
SubjectType = Literal["architecture", "vehicle", "landscape", "prop", "character", "original", "railway", "other"]
Template = Literal["building", "box"]
InputUnit = Literal["m", "cm", "mm"]


class ModelSpec(BaseModel):
    name: str = Field(default="Untitled paper model", min_length=1, max_length=80)
    scale: int = Field(default=150, ge=1, le=500)
    width_m: float = Field(default=18.0, gt=0, le=100)
    depth_m: float = Field(default=8.0, gt=0, le=100)
    height_m: float = Field(default=7.5, gt=0, le=50, description="Eave / wall height")
    overhang_m: float = Field(default=0.3, ge=0, le=2)
    pitch_deg: float = Field(default=30, ge=0, le=60)
    style: Style = "standard"
    roof: Roof = "gable"
    subject_type: SubjectType = "architecture"
    template: Template = "building"
    input_unit: InputUnit = "m"  # Display preference; actual dimensions remain metres.

    @model_validator(mode="after")
    def check(self):
        if self.template == "building" and self.roof == "gable" and self.pitch_deg < 5:
            raise ValueError("Gable roof pitch must be at least 5 degrees")
        return self


def miniature_mm(real_m: float, scale: int) -> float:
    return 1000.0 * real_m / scale


COLORS = {
    "faithful": ("#e6dcc7", "#554f4c", "#e5f2f4"),
    "standard": ("#e9dfcc", "#806447", "#afcfdf"),
    "anime": ("#fff2c5", "#ce6f6a", "#a4d9f0"),
    "retro": ("#cbb58b", "#645344", "#b3c9bd"),
    "easy": ("#f4f4ed", "#777777", "#d9e6ea"),
}


def rect(g, x, y, w, h, fill="none", stroke="#333333", kind="detail"):
    g.append({"type": "rect", "x": x, "y": y, "w": w, "h": h,
              "fill": fill, "stroke": stroke, "kind": kind})


def line(g, x1, y1, x2, y2, kind="detail", stroke="#333333"):
    g.append({"type": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
              "kind": kind, "stroke": stroke})


def polygon(g, points, fill="none", kind="cut", stroke="#333333"):
    g.append({"type": "poly", "points": points, "fill": fill,
              "kind": kind, "stroke": stroke})


def wall_part(title: str, width: float, height: float, rise: float, spec: ModelSpec,
              facade: bool = False, door: bool = False) -> dict:
    wall_color, _, glass_color = COLORS[spec.style]
    g = []
    x, y = 5.0, 5.0 + rise
    if rise:
        # The triangular gable and lower wall are ONE piece: no cut at the eave.
        polygon(g, [(x, y + height), (x, y), (x + width / 2, 5),
                    (x + width, y), (x + width, y + height)], wall_color)
        line(g, x, y, x + width, y, "detail", "#b8a991")
    else:
        rect(g, x, y, width, height, wall_color, kind="cut")
    # Separate glue tabs at left, right and bottom; dashed lines are folds.
    tab_top = y + min(4, height / 5)
    tab_bottom = y + height - min(4, height / 5)
    polygon(g, [(x, tab_top), (0, tab_top + 2), (0, tab_bottom - 2), (x, tab_bottom)],
            "#f4eadb")
    polygon(g, [(x + width, tab_top), (x + width + 5, tab_top + 2),
                (x + width + 5, tab_bottom - 2), (x + width, tab_bottom)], "#f4eadb")
    polygon(g, [(x + 4, y + height), (x + width - 4, y + height),
                (x + width - 6, y + height + 5), (x + 6, y + height + 5)], "#f4eadb")
    line(g, x, tab_top, x, tab_bottom, "fold")
    line(g, x + width, tab_top, x + width, tab_bottom, "fold")
    line(g, x + 4, y + height, x + width - 4, y + height, "fold")
    if spec.style != "easy":
        line(g, x, y + height * 0.18, x + width, y + height * 0.18,
             "detail", "#b8a991")
    # Windows and doors are printed details, not holes requiring cutting.
    count = 2 if facade else min(7, max(1, round(width / 23)))
    window_w = min(max(3, miniature_mm(1.2, spec.scale)), max(3, width / (count * 3)))
    window_h = min(height * 0.42, max(4, miniature_mm(1.5, spec.scale)))
    wy = y + max(3, height * 0.25)
    for i in range(count):
        wx = x + width * (i + 1) / (count + 1) - window_w / 2
        if door and abs((wx + window_w / 2) - (x + width / 2)) < window_w:
            continue
        rect(g, wx, wy, window_w, window_h, glass_color)
        if spec.style != "easy":
            line(g, wx + window_w / 2, wy, wx + window_w / 2, wy + window_h,
                 stroke="#758893")
            line(g, wx, wy + window_h / 2, wx + window_w, wy + window_h / 2,
                 stroke="#758893")
    if door:
        door_w = min(width * 0.2, max(5, miniature_mm(1.6, spec.scale)))
        door_h = min(height * 0.65, max(7, miniature_mm(2.3, spec.scale)))
        dx = x + (width - door_w) / 2
        dy = y + height - door_h
        rect(g, dx, dy, door_w, door_h, "#756554")
        rect(g, dx + door_w * 0.12, dy + door_h * 0.12,
             door_w * 0.76, door_h * 0.36, glass_color)
    return {"name": title, "w": width + 10, "h": y + height + 5,
            "graphics": g}


def roof_part(title: str, width: float, slope: float, spec: ModelSpec,
              first: bool) -> dict:
    _, roof_color, _ = COLORS[spec.style]
    g = []
    x, y = 5.0, 5.0
    rect(g, x, y, width, slope, roof_color, kind="cut")
    if first:
        polygon(g, [(x, y), (x + width, y),
                    (x + width - 2, 1), (x + 2, 1)], "#eadfce")
        line(g, x, y, x + width, y, "fold")
    if spec.style != "easy":
        n = max(1, int(slope // 4))
        for k in range(1, n + 1):
            yy = y + slope * k / (n + 1)
            line(g, x, yy, x + width, yy, stroke="#66594f")
    return {"name": title, "w": width + 10, "h": slope + 10,
            "graphics": g}


def box_panel(title: str, width: float, height: float, spec: ModelSpec,
              *, tabs: bool = True) -> dict:
    """A printed cuboid panel, with cut-contour and fold-tabs (not a 3-D reconstruction)."""
    g = []
    wall_color = COLORS[spec.style][0]
    x, y = 6.0, 6.0
    if tabs:
        tab = min(4.0, width / 8, height / 8)
        margin = min(4.0, width / 6, height / 6)
        polygon(g, [
            (x, y), (x + margin, y),
            (x + margin + tab / 2, y - tab), (x + width - margin - tab / 2, y - tab),
            (x + width - margin, y), (x + width, y), (x + width, y + height),
            (x + width - margin, y + height),
            (x + width - margin - tab / 2, y + height + tab),
            (x + margin + tab / 2, y + height + tab),
            (x + margin, y + height), (x, y + height),
            (x, y + height - margin),
            (x - tab, y + height - margin - tab / 2),
            (x - tab, y + margin + tab / 2),
            (x, y + margin),
        ], wall_color)
        line(g, x + margin, y, x + width - margin, y, "fold")
        line(g, x + margin, y + height, x + width - margin, y + height, "fold")
        line(g, x, y + margin, x, y + height - margin, "fold")
    else:
        rect(g, x, y, width, height, wall_color, kind="cut")
    return {"name": title, "w": width + 12, "h": height + 12, "graphics": g}


def box_parts(spec: ModelSpec) -> list[dict]:
    w = miniature_mm(spec.width_m, spec.scale)
    d = miniature_mm(spec.depth_m, spec.scale)
    h = miniature_mm(spec.height_m, spec.scale)
    return [
        box_panel("Front face", w, h, spec),
        box_panel("Back face", w, h, spec),
        box_panel("Left face", d, h, spec),
        box_panel("Right face", d, h, spec),
        box_panel("Top face", w, d, spec, tabs=False),
        box_panel("Bottom face", w, d, spec, tabs=False),
    ]


def build_parts(spec: ModelSpec) -> list[dict]:
    if spec.template == "box":
        return box_parts(spec)
    w = miniature_mm(spec.width_m, spec.scale)
    d = miniature_mm(spec.depth_m, spec.scale)
    h = miniature_mm(spec.height_m, spec.scale)
    o = miniature_mm(spec.overhang_m, spec.scale)
    rise = (d / 2) * tan(radians(spec.pitch_deg)) if spec.roof == "gable" else 0
    parts = [
        wall_part("Front wall", w, h, 0, spec, True, True),
        wall_part("Back wall", w, h, 0, spec, True, False),
        # The ridge runs along the width, so the triangular gables sit on the depth walls.
        wall_part("Left wall", d, h, rise, spec),
        wall_part("Right wall", d, h, rise, spec),
    ]
    if spec.roof == "gable":
        slope = (d / 2 + o) / cos(radians(spec.pitch_deg))
        parts += [
            roof_part("Roof A", w + 2 * o, slope, spec, True),
            roof_part("Roof B", w + 2 * o, slope, spec, False),
        ]
    else:
        parts.append(roof_part("Flat roof", w + 2 * o, d + 2 * o, spec, False))
    return parts


def _num_tiles(length: float, area: float) -> int:
    return 1 if length <= area else 1 + ceil((length - area) / (area - OVERLAP))


def page_jobs(spec: ModelSpec) -> list[dict]:
    jobs = []
    for part in build_parts(spec):
        nx = _num_tiles(part["w"], AREA_W)
        ny = _num_tiles(part["h"], AREA_H)
        for yi in range(ny):
            for xi in range(nx):
                jobs.append({"part": part, "x": xi * (AREA_W - OVERLAP),
                             "y": yi * (AREA_H - OVERLAP),
                             "tile": (xi + 1, yi + 1, nx, ny)})
    if len(jobs) > 100:
        raise ValueError("The model requires over 100 A4 pages; use a smaller model or scale")
    return jobs


def summary(spec: ModelSpec) -> dict:
    d = miniature_mm(spec.depth_m, spec.scale)
    rise = d / 2 * tan(radians(spec.pitch_deg)) if spec.template == "building" and spec.roof == "gable" else 0
    jobs = page_jobs(spec)
    return {
        "size_mm": {
            "width": round(miniature_mm(spec.width_m, spec.scale), 1),
            "depth": round(d, 1),
            "wall_height": round(miniature_mm(spec.height_m, spec.scale), 1),
            "total_height": round(miniature_mm(spec.height_m, spec.scale) + rise, 1),
        },
        "scale": spec.scale,
        "subject_type": spec.subject_type,
        "template": spec.template,
        "parts": [{"name": p["name"], "width_mm": round(p["w"], 1),
                   "height_mm": round(p["h"], 1)} for p in build_parts(spec)],
        "pages": len(jobs),
        "warnings": [
            "Dimensions are supplied by the user, not verified from online sources.",
            ("Windows and doors are illustrative printed details." if spec.template == "building"
             else "Box template is a basic cuboid, not an automatic reconstruction of the subject."),
            "Large parts are tiled with 5 mm overlap for assembly.",
        ],
    }


def _svg_graphic(g: dict) -> str:
    s = ' stroke="' + g["stroke"] + '" stroke-width="0.25"'
    if g["kind"] == "fold":
        s += ' stroke-dasharray="2,1"'
    fill = g.get("fill", "none")
    if g["type"] == "rect":
        return ('<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"'.format(
            **g) + s + '/>')
    if g["type"] == "line":
        return ('<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'.format(**g)
                + s + '/>')
    points = " ".join(str(x) + "," + str(y) for x, y in g["points"])
    return '<polygon points="' + points + '" fill="' + fill + '"' + s + '/>'


def render_svg(spec: ModelSpec, page: int = 0) -> str:
    jobs = page_jobs(spec)
    if page < 0 or page >= len(jobs):
        raise IndexError("Page not found")
    job = jobs[page]
    part = job["part"]
    xoffset, yoffset = AREA_X - job["x"], AREA_Y - job["y"]
    label = escape(spec.name + " | " + part["name"] + " | 1/" + str(spec.scale))
    graphics = "".join(_svg_graphic(g) for g in part["graphics"])
    tx, ty, nx, ny = job["tile"]
    header = '<?xml version="1.0" encoding="utf-8"?>'
    header += ('<svg xmlns="http://www.w3.org/2000/svg" '
               'width="210mm" height="297mm" viewBox="0 0 210 297">')
    header += '<rect width="210" height="297" fill="white"/>'
    header += '<text x="12" y="17" font-family="sans-serif" font-size="4.3">' + label + '</text>'
    header += ('<text x="198" y="23" font-family="sans-serif" text-anchor="end" '
               'font-size="3">Tile {}/{}, page {}/{}</text>'.format(
                   tx, nx, page + 1, len(jobs)))
    header += ('<defs><clipPath id="area"><rect x="12" y="28" width="186" '
               'height="225"/></clipPath></defs>')
    header += '<g clip-path="url(#area)" transform="translate({},{})">'.format(
        xoffset, yoffset) + graphics + '</g>'
    header += ('<rect x="12" y="28" width="186" height="225" fill="none" '
               'stroke="#bbb" stroke-width=".12"/>')
    header += ('<line x1="14" y1="278" x2="64" y2="278" stroke="black" stroke-width=".4"/>'
               '<line x1="14" y1="276" x2="14" y2="280" stroke="black" stroke-width=".3"/>'
               '<line x1="64" y1="276" x2="64" y2="280" stroke="black" stroke-width=".3"/>'
               '<text x="14" y="284" font-size="3.2">50 mm CHECK - PRINT AT 100%</text>'
               '<text x="14" y="290" font-size="2.8">Solid: cut | Dashed: fold | A4</text></svg>')
    return header


def _pdf_graphic(c: canvas.Canvas, g: dict, shift_x: float, shift_y: float) -> None:
    c.setStrokeColor(HexColor(g["stroke"]))
    c.setLineWidth(0.25 * mm)
    c.setDash(2 * mm, 1 * mm) if g["kind"] == "fold" else c.setDash()
    fill = g.get("fill", "none")
    if fill != "none":
        c.setFillColor(HexColor(fill))

    def px(x: float) -> float:
        return (x + shift_x) * mm

    def py(y: float) -> float:
        return (PAGE_H - y - shift_y) * mm

    if g["type"] == "rect":
        c.rect(px(g["x"]), py(g["y"] + g["h"]), g["w"] * mm, g["h"] * mm,
               fill=int(fill != "none"), stroke=1)
    elif g["type"] == "line":
        c.line(px(g["x1"]), py(g["y1"]), px(g["x2"]), py(g["y2"]))
    else:
        p = c.beginPath()
        first = g["points"][0]
        p.moveTo(px(first[0]), py(first[1]))
        for x, y in g["points"][1:]:
            p.lineTo(px(x), py(y))
        p.close()
        c.drawPath(p, fill=int(fill != "none"), stroke=1)
    c.setDash()


def render_pdf(spec: ModelSpec) -> bytes:
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=A4)
    jobs = page_jobs(spec)
    for index, job in enumerate(jobs):
        part = job["part"]
        c.setFont("Helvetica", 11)
        c.drawString(12 * mm, (PAGE_H - 17) * mm,
                     (spec.name.encode("ascii", "ignore").decode() or "Model")[:34]
                     + " | " + part["name"] + " | 1/" + str(spec.scale))
        c.setFont("Helvetica", 8)
        c.drawRightString(198 * mm, (PAGE_H - 23) * mm,
                          "Page " + str(index + 1) + "/" + str(len(jobs)))
        c.saveState()
        p = c.beginPath()
        p.rect(AREA_X * mm, (PAGE_H - AREA_Y - AREA_H) * mm,
               AREA_W * mm, AREA_H * mm)
        c.clipPath(p, stroke=0, fill=0)
        for graphic in part["graphics"]:
            _pdf_graphic(c, graphic, AREA_X - job["x"], AREA_Y - job["y"])
        c.restoreState()
        c.setStrokeColor(HexColor("#bbbbbb"))
        c.rect(AREA_X * mm, (PAGE_H - AREA_Y - AREA_H) * mm,
               AREA_W * mm, AREA_H * mm, fill=0, stroke=1)
        c.setStrokeColor(HexColor("#111111"))
        c.setLineWidth(0.4 * mm)
        c.line(14 * mm, (PAGE_H - 278) * mm, 64 * mm, (PAGE_H - 278) * mm)
        c.setFont("Helvetica", 8)
        c.drawString(14 * mm, (PAGE_H - 284) * mm,
                     "50 mm CHECK - PRINT AT 100%")
        c.drawString(14 * mm, (PAGE_H - 290) * mm,
                     "Solid = cut / Dashed = fold / A4")
        c.showPage()
    c.save()
    return output.getvalue()
