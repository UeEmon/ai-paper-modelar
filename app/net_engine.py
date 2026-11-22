"""Parametric, dimension-driven printable nets for simple solids.

All geometry is in model millimetres. Output primitives are compatible with
generator.py's SVG/PDF exporters; no AI-generated geometry is trusted here.

Supported: circular cylinder, conical frustum/cone, regular polygon prism,
and regular polygon pyramid. Curved edges are approximated to at most 1.5 mm
arc segment lengths and have no more than 512 vertices per arc.
"""
from __future__ import annotations

from math import ceil, cos, hypot, pi, sin, sqrt
from typing import Any

# These graphics match the existing generator's public part shape.
Graphic = dict[str, Any]


def _poly(points, fill="#e6e6e6", kind="cut") -> Graphic:
    return {
        "type": "poly", "points": list(points), "fill": fill,
        "kind": kind, "stroke": "#333333",
    }


def _line(p, q, kind="fold") -> Graphic:
    return {
        "type": "line", "x1": p[0], "y1": p[1], "x2": q[0],
        "y2": q[1], "kind": kind, "stroke": "#333333",
    }


def _coordinates(graphic: Graphic):
    if graphic["type"] == "poly":
        return graphic["points"]
    if graphic["type"] == "line":
        return [(graphic["x1"], graphic["y1"]),
                (graphic["x2"], graphic["y2"])]
    if graphic["type"] == "rect":
        return [(graphic["x"], graphic["y"]),
                (graphic["x"] + graphic["w"], graphic["y"] + graphic["h"])]
    raise ValueError("Unsupported graphic")


def _part(name: str, graphics: list[Graphic]) -> dict:
    """Tight bounds and consistent 6 mm safety border for every primitive."""
    pts = [point for graphic in graphics for point in _coordinates(graphic)]
    if not pts:
        raise ValueError("Part has no graphics")
    min_x = min(x for x, _ in pts)
    min_y = min(y for _, y in pts)
    max_x = max(x for x, _ in pts)
    max_y = max(y for _, y in pts)
    shift_x, shift_y = 6 - min_x, 6 - min_y
    shifted = []
    for g in graphics:
        item = dict(g)
        if item["type"] == "poly":
            item["points"] = [(x + shift_x, y + shift_y) for x, y in g["points"]]
        elif item["type"] == "line":
            for key in ("x1", "x2"):
                item[key] += shift_x
            for key in ("y1", "y2"):
                item[key] += shift_y
        else:
            item["x"] += shift_x
            item["y"] += shift_y
        shifted.append(item)
    return {
        "name": name,
        "w": max_x - min_x + 12,
        "h": max_y - min_y + 12,
        "graphics": shifted,
    }


def _regular_vertices(radius: float, sides: int):
    """Circumcircle centred on origin; side length = 2*r*sin(pi/n)."""
    return [
        (radius * cos(-pi / 2 + 2 * pi * i / sides),
         radius * sin(-pi / 2 + 2 * pi * i / sides))
        for i in range(sides)
    ]


def _rounded_vertices(radius: float):
    sides = max(48, min(512, ceil(2 * pi * radius / 1.5)))
    return _regular_vertices(radius, sides)


def _cap(name: str, radius: float, fill: str, sides: int | None = None) -> dict:
    vertices = _regular_vertices(radius, sides) if sides else _rounded_vertices(radius)
    return _part(name, [_poly(vertices, fill)])


def _cap_with_tabs(name: str, radius: float, fill: str,
                   sides: int | None = None) -> dict:
    """Cap with per-edge external glue flaps and scored tab roots.

    The cap's primary polygon is circumscribed by the stated radius.
    For round caps, chords approximate a circle; folded tabs attach the
    cap to the cone wall. Regular polygon caps use the exact side count.
    """
    n = sides if sides else max(16, min(64, ceil(2 * pi * radius / 8)))
    verts = _regular_vertices(radius, n)
    contour = []
    scores = []
    for i, p in enumerate(verts):
        q = verts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        side = hypot(dx, dy)
        ux, uy = dx / side, dy / side
        nx, ny = uy, -ux
        margin = min(1.2, side * 0.14)
        tab = min(3.5, side * 0.15)
        root0 = (p[0] + ux * margin, p[1] + uy * margin)
        root1 = (q[0] - ux * margin, q[1] - uy * margin)
        contour.extend([
            p, root0,
            (root0[0] + nx * tab, root0[1] + ny * tab),
            (root1[0] + nx * tab, root1[1] + ny * tab),
            root1,
        ])
        scores.append(_line(root0, root1))
    return _part(name, [_poly(contour, fill)] + scores)


def _strip(name: str, widths: list[float], height: float, fill: str,
           *, score_panel_edges: bool = True) -> dict:
    """One continuous strip with tabs on top, bottom and end seam.

    Fold borders are NOT cut through: cut graphics contain only an outer
    contour. Each tab meets the strip at a dashed score line.
    """
    total = sum(widths)
    if total <= 0 or height <= 0:
        raise ValueError("Strip dimensions must be positive")
    xs = [0.0]
    for width in widths:
        xs.append(xs[-1] + width)
    smallest = min(widths)
    tab_depth = min(4.0, smallest * 0.18, height * 0.17)
    seam_depth = min(5.0, height * 0.22)
    setback = min(height * 0.14, 2.0)
    graphics: list[Graphic] = []
    upper = [(0.0, 0.0)]
    for left, right in zip(xs[:-1], xs[1:]):
        margin = min((right - left) * 0.16, 1.4)
        upper.extend([
            (left + margin, 0),
            (left + margin + tab_depth * 0.25, -tab_depth),
            (right - margin - tab_depth * 0.25, -tab_depth),
            (right - margin, 0),
            (right, 0),
        ])
        graphics.append(_line((left + margin, 0), (right - margin, 0)))
        graphics.append(_line((left + margin, height), (right - margin, height)))

    # Seam tab joins the first and last body edges.
    outline = upper + [
        (total, setback),
        (total + seam_depth, setback + min(1, seam_depth * 0.25)),
        (total + seam_depth, height - setback - min(1, seam_depth * 0.25)),
        (total, height - setback),
        (total, height),
    ]
    for left, right in reversed(list(zip(xs[:-1], xs[1:]))):
        margin = min((right - left) * 0.16, 1.4)
        outline.extend([
            (right - margin, height),
            (right - margin - tab_depth * 0.25, height + tab_depth),
            (left + margin + tab_depth * 0.25, height + tab_depth),
            (left + margin, height),
            (left, height),
        ])
    outline.append((0, 0))
    graphics.insert(0, _poly(outline, fill))
    graphics.append(_line((total, setback), (total, height - setback)))
    if score_panel_edges:
        for boundary in xs[1:-1]:
            graphics.append(_line((boundary, 0), (boundary, height)))
    return _part(name, graphics)


def _frustum_side(bottom_radius: float, top_radius: float,
                  wall_height: float, fill: str) -> dict:
    """Exact annular-sector development (polyline approximation of arcs).

    For a frustum: slant s=sqrt(h^2+(r0-r1)^2);
    outer sector radius R=s*r0/(r0-r1); angle=2*pi*r0/R.
    """
    if not 0 <= top_radius < bottom_radius:
        raise ValueError("Frustum requires top radius less than bottom radius")
    slant = hypot(wall_height, bottom_radius - top_radius)
    radial_delta = bottom_radius - top_radius
    outer_r = slant * bottom_radius / radial_delta
    inner_r = slant * top_radius / radial_delta
    angle = 2 * pi * bottom_radius / outer_r
    count = max(32, min(512, ceil(2 * pi * bottom_radius / 1.5)))
    a0 = -angle / 2
    a1 = angle / 2
    outer = [
        (outer_r * cos(a0 + angle * i / count),
         outer_r * sin(a0 + angle * i / count))
        for i in range(count + 1)
    ]
    inner = [
        (inner_r * cos(a0 + angle * i / count),
         inner_r * sin(a0 + angle * i / count))
        for i in reversed(range(count + 1))
    ] if top_radius > 0 else [(0.0, 0.0)]
    core = outer + inner
    # A seam flap along the radial edge from innermost left to outermost left.
    start, end = core[-1], core[0]
    vx = end[0] - start[0]
    vy = end[1] - start[1]
    span = hypot(vx, vy)
    ux, uy = vx / span, vy / span
    area = sum(
        core[i][0] * core[(i+1) % len(core)][1] -
        core[(i+1) % len(core)][0] * core[i][1]
        for i in range(len(core))
    )
    # For positive signed screen-space polygon area the outside is on the
    # right of the oriented edge; otherwise it is on the left.
    nx, ny = ((uy, -ux) if area > 0 else (-uy, ux))
    tab = min(4.0, span * 0.17)
    setback = min(1.5, span * 0.12)
    flap = [
        (start[0] + ux * setback, start[1] + uy * setback),
        (start[0] + ux * setback + nx * tab,
         start[1] + uy * setback + ny * tab),
        (end[0] - ux * setback + nx * tab,
         end[1] - uy * setback + ny * tab),
        (end[0] - ux * setback, end[1] - uy * setback),
    ]
    return _part("Cone side", [
        _poly(core + flap, fill),
        _line(start, end),
    ])


def _pyramid_face(name: str, side: float, face_altitude: float,
                  fill: str) -> dict:
    """Single triangular face with a seam tab on its left diagonal."""
    a = (side / 2, 0.0)
    b = (side, face_altitude)
    c = (0.0, face_altitude)
    dx, dy = a[0] - c[0], a[1] - c[1]
    length = hypot(dx, dy)
    ux, uy = dx / length, dy / length
    # Positive winding (a,b,c): outward of edge c->a is (dy,-dx).
    nx, ny = (uy, -ux)
    tab = min(4.0, side * 0.14, length * 0.14)
    setback = min(1.5, length * 0.1)
    outline = [
        a, b, c,
        (c[0] + ux * setback, c[1] + uy * setback),
        (c[0] + ux * setback + nx * tab, c[1] + uy * setback + ny * tab),
        (a[0] - ux * setback + nx * tab, a[1] - uy * setback + ny * tab),
        (a[0] - ux * setback, a[1] - uy * setback),
    ]
    return _part(name, [_poly(outline, fill), _line(c, a)])


def build_parametric_parts(spec, color: str) -> list[dict]:
    """Create template parts; bounding dimensions are taken from actual geometry."""
    mm = lambda metres: 1000.0 * metres / spec.scale
    radius = mm(spec.width_m) / 2
    height = mm(spec.height_m)
    if spec.template == "cylinder":
        perimeter = 2 * pi * radius
        return [
            _strip("Cylinder side", [perimeter / 24] * 24, height, color,
                   score_panel_edges=False),
            _cap("Top cap", radius, color),
            _cap("Bottom cap", radius, color),
        ]
    if spec.template == "cone":
        top_radius = radius * spec.top_ratio
        if spec.top_ratio == 1:
            return [
                _strip("Cylinder side", [2 * pi * radius / 24] * 24,
                       height, color, score_panel_edges=False),
                _cap("Top cap", radius, color),
                _cap("Bottom cap", radius, color),
            ]
        parts = [_frustum_side(radius, top_radius, height, color),
                 _cap_with_tabs("Bottom cap", radius, color)]
        if top_radius > 0:
            parts.append(_cap_with_tabs("Top cap", top_radius, color))
        return parts
    if spec.template == "prism":
        side = 2 * radius * sin(pi / spec.sides)
        return [
            _strip("Prism side", [side] * spec.sides, height, color),
            _cap("Top polygon", radius, color, spec.sides),
            _cap("Bottom polygon", radius, color, spec.sides),
        ]
    if spec.template == "pyramid":
        side = 2 * radius * sin(pi / spec.sides)
        apothem = radius * cos(pi / spec.sides)
        altitude = hypot(height, apothem)
        return [_cap_with_tabs("Base polygon", radius, color, spec.sides)] + [
            _pyramid_face("Triangle " + str(i + 1), side, altitude, color)
            for i in range(spec.sides)
        ]
    raise ValueError("Unsupported parametric template")
