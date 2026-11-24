"""Assembly guide page for a mesh paper net.

One A4 page, printed before the part sheets: a legend of the line types, the
model seen from the front and the back with each part shaded and numbered, and
an assembly order that says which part to glue to which, by edge number.
"""
from __future__ import annotations

import os
from math import cos, radians, sin, sqrt
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

PAGE_W, PAGE_H = 210.0, 297.0
# A Japanese TrueType font embedded (subset) into the PDF, so every viewer
# shows the guide. The Docker image installs IPAex Gothic. Without one, fall
# back to a standard CID font that the viewer must supply itself.
JP_FONT_FILES = [os.environ.get("PAPER_MODELAR_JP_FONT", ""),
                 "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
                 "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]
PALETTE = ["#e8b4a0", "#a9c8e8", "#b9dca4", "#f0d58c", "#cdb4e4",
           "#9fd8cf", "#f2b8cf", "#d9c7a7", "#b7c0ee", "#e6c3a0"]
MAX_STEPS = 18


def assembly_order(guide: dict) -> list[dict]:
    """Largest part first, then always the part sharing the most edges with
    what is already built. Each step names the edge numbers to glue."""
    pieces = guide["pieces"]
    size = [0] * (pieces + 1)
    for piece in guide["piece_of"]:
        size[piece] += 1
    links: dict[tuple[int, int], list[int]] = {}
    for number, a, b in guide["seams"]:
        if a != b:
            links.setdefault((min(a, b), max(a, b)), []).append(number)
    built: list[int] = []
    remaining = set(range(1, pieces + 1))
    steps = []
    while remaining:
        def shared(piece):
            return [n for other in built
                    for n in links.get((min(piece, other), max(piece, other)), [])]
        piece = max(remaining, key=lambda p: (len(shared(p)), size[p], -p))
        glue = {}
        for other in built:
            numbers = links.get((min(piece, other), max(piece, other)))
            if numbers:
                glue[other] = sorted(numbers)
        steps.append({"piece": piece, "triangles": size[piece], "glue": glue})
        built.append(piece)
        remaining.discard(piece)
    return steps


def _shade(hex_color: str, light: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    k = 0.62 + 0.38 * light
    return "#" + "".join("{:02x}".format(max(0, min(255, round(c * k)))) for c in (r, g, b))


def _view(guide: dict, azimuth: float, box: tuple[float, float, float, float],
          z_up: bool) -> tuple[list, list]:
    """Faces (painter's order) and part labels of one view fitted in box."""
    points = guide["points"]
    if not z_up:  # OBJ is usually Y-up: turn it to Z-up.
        points = [(x, -z, y) for x, y, z in points]
    a, e = radians(azimuth), radians(28)
    toward = (cos(e) * cos(a), cos(e) * sin(a), sin(e))
    right = (-sin(a), cos(a), 0.)
    up = (-sin(e) * cos(a), -sin(e) * sin(a), cos(e))
    dot = lambda p, q: p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
    flat = [(dot(p, right), -dot(p, up)) for p in points]
    x0, x1 = min(p[0] for p in flat), max(p[0] for p in flat)
    y0, y1 = min(p[1] for p in flat), max(p[1] for p in flat)
    bx, by, bw, bh = box
    k = min(bw / max(x1 - x0, 1e-9), bh / max(y1 - y0, 1e-9))
    ox = bx + (bw - (x1 - x0) * k) / 2 - x0 * k
    oy = by + (bh - (y1 - y0) * k) / 2 - y0 * k
    screen = [(ox + x * k, oy + y * k) for x, y in flat]
    faces = []
    sums: dict[int, list[float]] = {}
    for fi, face in enumerate(guide["faces"]):
        pa, pb, pc = (points[i] for i in face)
        u = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        v = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = sqrt(dot(n, n)) or 1.
        facing = dot(n, toward) / length
        centre = tuple((pa[i] + pb[i] + pc[i]) / 3 for i in range(3))
        piece = guide["piece_of"][fi]
        color = _shade(PALETTE[(piece - 1) % len(PALETTE)], abs(facing))
        faces.append((dot(centre, toward), [screen[i] for i in face], color))
        # Label a part where its faces turn towards the viewer, weighted by
        # their on-screen area, so the number sits on a visible side.
        if guide["oriented"] and facing <= 0.15:
            continue
        (ax, ay), (bx2, by2), (cx, cy) = (screen[i] for i in face)
        area = abs((bx2 - ax) * (cy - ay) - (by2 - ay) * (cx - ax)) / 2
        total = sums.setdefault(piece, [0., 0., 0., -1e18])
        total[0] += area * (ax + bx2 + cx) / 3
        total[1] += area * (ay + by2 + cy) / 3
        total[2] += area
        total[3] = max(total[3], dot(centre, toward))
    faces.sort(key=lambda f: f[0])
    labels = [(piece, sx / w, sy / w) for piece, (sx, sy, w, _) in sums.items() if w > 0.5]
    return faces, labels


def build_page(guide: dict, *, name: str, scale: int, size_mm: list[float],
               z_up: bool, part_pages: dict[int, list[int]], total_pages: int) -> list[dict]:
    """The guide page as simple drawing items in page millimetres."""
    items: list[dict] = []

    def text(x, y, s, size=3.2, fill="#222222", anchor="start", bold=False):
        items.append({"t": "text", "x": x, "y": y, "s": s, "size": size,
                      "fill": fill, "anchor": anchor, "bold": bold})

    def line(x1, y1, x2, y2, stroke="#333333", dash=None, width=0.35):
        items.append({"t": "line", "p": [(x1, y1), (x2, y2)], "stroke": stroke,
                      "dash": dash, "width": width})

    def poly(points, fill, stroke="none", width=0.1):
        items.append({"t": "poly", "p": points, "fill": fill, "stroke": stroke,
                      "width": width})

    text(12, 18, "組み立て説明", 6, bold=True)
    text(12, 25, "{}　1/{}　完成寸法 約 {} mm".format(
        name[:40], scale, " × ".join(str(round(v)) for v in size_mm)), 3.2, "#444444")
    text(198, 18, "1 / {} ページ".format(total_pages), 3, "#444444", "end")

    # Legend.
    y = 34
    legend = [
        ("実線", "切る", lambda yy: line(14, yy, 34, yy)),
        ("赤の一点鎖線", "山折り（印刷面が外側）",
         lambda yy: line(14, yy, 34, yy, "#a8321f", (3, .8, .6, .8))),
        ("青の破線", "谷折り（印刷面が内側）",
         lambda yy: line(14, yy, 34, yy, "#1f56a8", (2, 1))),
        ("薄い色の帯", "のりしろ（裏側に折って貼る）",
         lambda yy: poly([(14, yy - 2), (34, yy - 2), (32, yy + 1.5), (16, yy + 1.5)],
                         "#f1e5cb", "#333333", .25)),
        ("同じ番号", "同じ番号の辺どうしを貼り合わせる",
         lambda yy: text(24, yy + 1.1, "12", 3, "#7a2e1f", "middle")),
    ]
    if not guide["oriented"]:
        legend[1] = ("破線", "折る（山谷はモデルの向きから判定できませんでした）",
                     lambda yy: line(14, yy, 34, yy, "#333333", (2, 1)))
        del legend[2]
    for label, meaning, sample in legend:
        sample(y)
        text(38, y + 1.1, label, 3, "#222222", bold=True)
        text(72, y + 1.1, meaning, 3, "#444444")
        y += 6.5

    # Two views with the part numbers.
    view_top = y + 2
    text(12, view_top + 3, "前から見た図", 3, "#444444")
    text(108, view_top + 3, "後ろから見た図", 3, "#444444")
    for azimuth, box in ((-55., (12, view_top + 5, 90, 78)),
                         (125., (108, view_top + 5, 90, 78))):
        faces, labels = _view(guide, azimuth, box, z_up)
        for _, points, color in faces:
            poly(points, color, color, .12)
        for piece, x, yy in labels:
            items.append({"t": "badge", "x": x, "y": yy, "s": str(piece)})

    # Steps.
    y = view_top + 92
    text(12, y, "組み立ての順番", 4, bold=True)
    y += 6
    text(14, y, "1. 100%（実寸）で印刷し、50mmの目盛りで大きさを確かめます。", 3, "#333333")
    y += 5
    text(14, y, "2. 切る前に、折り線に定規で筋を付けておくときれいに折れます。", 3, "#333333")
    y += 5
    text(14, y, "3. 下の順に部品を組み、同じ番号の辺をのりしろで貼り合わせます。", 3, "#333333")
    y += 7
    steps = assembly_order(guide)
    for index, step in enumerate(steps[:MAX_STEPS], 1):
        pages = part_pages.get(step["piece"], [])
        where = "（{}ページ）".format("・".join(str(p) for p in pages)) if pages else ""
        head = "{:>2}. 部品{}{}".format(index, step["piece"], where)
        if not step["glue"] and index == 1:
            detail = "まず部品の中の同じ番号どうしを貼り、形を作ります。"
        elif not step["glue"]:
            detail = "ほかの部品と辺を共有しない独立した形です。形を作り、上の図の位置に貼り付けます。"
        else:
            parts = []
            for other, numbers in step["glue"].items():
                shown = ", ".join(str(n) for n in numbers[:6])
                if len(numbers) > 6:
                    shown += " ほか{}か所".format(len(numbers) - 6)
                parts.append("部品{}と {}".format(other, shown))
            detail = "／".join(parts)
        text(14, y, head, 3, "#222222", bold=True)
        for row in _wrap(detail, 46, 2):
            text(56, y, row, 3, "#444444")
            y += 4.4
        y += 1.2
        if y > 284:
            break
    if len(steps) > MAX_STEPS or y > 284:
        text(14, min(y, 289), "…残りの部品も、同じ番号を手がかりに順に貼り合わせます。", 3, "#444444")
    return items


def _wrap(text: str, width: int, rows: int) -> list[str]:
    """Break after ", " or "／" so a number is never split; cut with … ."""
    tokens, start = [], 0
    for i, ch in enumerate(text):
        if ch in "／," and (ch == "／" or text[i + 1:i + 2] == " "):
            end = i + (2 if ch == "," else 1)
            tokens.append(text[start:end])
            start = end
    tokens.append(text[start:])
    lines = [""]
    for token in tokens:
        if lines[-1] and len(lines[-1]) + len(token) > width:
            if len(lines) == rows:
                lines[-1] = lines[-1].rstrip(", ／") + " …"
                return lines
            lines.append("")
        lines[-1] += token
    return lines


def to_svg(items: list[dict]) -> str:
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" '
           'viewBox="0 0 210 297" data-page="assembly-guide">',
           '<rect width="210" height="297" fill="white"/>']
    for item in items:
        if item["t"] == "text":
            anchor = {"start": "start", "middle": "middle", "end": "end"}[item["anchor"]]
            weight = ' font-weight="bold"' if item["bold"] else ""
            out.append('<text x="{:.2f}" y="{:.2f}" font-family="sans-serif" font-size="{}" '
                       'fill="{}" text-anchor="{}"{}>{}</text>'.format(
                           item["x"], item["y"], item["size"], item["fill"], anchor,
                           weight, escape(item["s"])))
        elif item["t"] == "line":
            (x1, y1), (x2, y2) = item["p"]
            dash = (' stroke-dasharray="' + ",".join(str(v) for v in item["dash"]) + '"'
                    if item["dash"] else "")
            out.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" '
                       'stroke-width="{}"{}/>'.format(x1, y1, x2, y2, item["stroke"],
                                                    item["width"], dash))
        elif item["t"] == "poly":
            points = " ".join("{:.2f},{:.2f}".format(x, y) for x, y in item["p"])
            out.append('<polygon points="{}" fill="{}" stroke="{}" stroke-width="{}" '
                       'stroke-linejoin="round"/>'.format(points, item["fill"],
                                                          item["stroke"], item["width"]))
        else:
            out.append('<circle cx="{:.2f}" cy="{:.2f}" r="2.6" fill="white" stroke="#222" '
                       'stroke-width=".3"/><text x="{:.2f}" y="{:.2f}" font-family="sans-serif" '
                       'font-size="3" font-weight="bold" text-anchor="middle" '
                       'dominant-baseline="central" data-layer="part-number">{}</text>'.format(
                           item["x"], item["y"], item["x"], item["y"], escape(item["s"])))
    out.append("</svg>")
    return "".join(out)


_jp_font: str | None = None


def _japanese_font() -> str:
    global _jp_font
    if _jp_font is None:
        for path in JP_FONT_FILES:
            if path and os.path.isfile(path):
                try:
                    pdfmetrics.registerFont(TTFont("GuideJP", path))
                    _jp_font = "GuideJP"
                    break
                except Exception:  # unreadable or unsupported font file
                    continue
        else:
            pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
            _jp_font = "HeiseiKakuGo-W5"
    return _jp_font


def draw_pdf(c, items: list[dict]) -> None:
    font = _japanese_font()
    px = lambda x: x * mm
    py = lambda y: (PAGE_H - y) * mm
    for item in items:
        c.saveState()
        if item["t"] == "text":
            c.setFillColor(HexColor(item["fill"]))
            c.setFont(font, item["size"] / 0.3528)
            draw = {"start": c.drawString, "middle": c.drawCentredString,
                    "end": c.drawRightString}[item["anchor"]]
            draw(px(item["x"]), py(item["y"]), item["s"])
        elif item["t"] == "line":
            c.setStrokeColor(HexColor(item["stroke"]))
            c.setLineWidth(item["width"] * mm)
            if item["dash"]:
                c.setDash([v * mm for v in item["dash"]])
            (x1, y1), (x2, y2) = item["p"]
            c.line(px(x1), py(y1), px(x2), py(y2))
        elif item["t"] == "poly":
            c.setFillColor(HexColor(item["fill"]))
            stroke = item["stroke"] != "none"
            if stroke:
                c.setStrokeColor(HexColor(item["stroke"]))
                c.setLineWidth(item["width"] * mm)
            path = c.beginPath()
            path.moveTo(px(item["p"][0][0]), py(item["p"][0][1]))
            for x, y in item["p"][1:]:
                path.lineTo(px(x), py(y))
            path.close()
            c.drawPath(path, fill=1, stroke=int(stroke))
        else:
            c.setFillColor(HexColor("#ffffff"))
            c.setStrokeColor(HexColor("#222222"))
            c.setLineWidth(.3 * mm)
            c.circle(px(item["x"]), py(item["y"]), 2.6 * mm, fill=1, stroke=1)
            c.setFillColor(HexColor("#222222"))
            c.setFont("Helvetica-Bold", 3 / 0.3528)
            c.drawCentredString(px(item["x"]), py(item["y"] + 1.05), item["s"])
        c.restoreState()
    c.showPage()
