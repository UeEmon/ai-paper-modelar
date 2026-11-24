"""Assembly aids on mesh nets: flat faces, mountain/valley folds, seam numbers."""
from __future__ import annotations

from collections import Counter, defaultdict
from math import cos, pi, sin
import re

from app.generator import ModelSpec, render_svg
from app.mesh_unfolder import _edge_type, _normal, parse_obj, unfold

CUBE_OBJ = b"""v 0 0 0
v 10 0 0
v 10 10 0
v 0 10 0
v 0 0 10
v 10 0 10
v 10 10 10
v 0 10 10
f 1 4 3 2
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""

L_OUTLINE = [(0, 0), (40, 0), (40, 15), (15, 15), (15, 40), (0, 40)]


def _obj(vertices, faces):
    lines = ["v {} {} {}".format(*v) for v in vertices]
    lines += ["f " + " ".join(str(i) for i in face) for face in faces]
    return "\n".join(lines).encode()


def _l_prism_triangles():
    vertices = [(x, y, 0) for x, y in L_OUTLINE] + [(x, y, 20) for x, y in L_OUTLINE]
    faces = []
    for i in range(6):
        j = (i + 1) % 6
        faces += [(i, j, j + 6), (i, j + 6, i + 6)]
    return vertices, faces


def _cylinder_obj(sides=16):
    vertices, faces = [], []
    for i in range(sides):
        a = 2 * pi * i / sides
        vertices += [(20 * cos(a), 20 * sin(a), 0), (20 * cos(a), 20 * sin(a), 40)]
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((2 * i + 1, 2 * j + 1, 2 * j + 2, 2 * i + 2))
    faces.append(tuple(2 * i + 1 for i in range(sides))[::-1])
    faces.append(tuple(2 * i + 2 for i in range(sides)))
    return _obj(vertices, faces)


def _graphics(net):
    return [g for part in net.parts for g in part["graphics"]]


def test_flat_faces_have_no_fold_line_across_them():
    net = unfold(parse_obj(CUBE_OBJ))
    stats = net.stats
    # Each square is two triangles; the diagonal between them is hidden.
    assert stats["flat_edges_hidden"] == 6
    assert stats["islands"] == 1
    # A cube net has 5 folds and 7 glued edges.
    assert stats["mountain_folds"] == 5
    assert stats["seams"] == 7
    body_folds = [g for g in _graphics(net)
                  if g["type"] == "line" and g["kind"] == "fold"]
    assert len(body_folds) == stats["mountain_folds"] + stats["tabs"]


def test_convex_edges_are_mountain_and_concave_edges_valley():
    vertices, faces = _l_prism_triangles()
    normals = [_normal(face, vertices) for face in faces]
    neighbours = defaultdict(list)
    for index, face in enumerate(faces):
        for k in range(3):
            neighbours[tuple(sorted((face[k], face[(k + 1) % 3])))].append(index)
    # Vertex 3 (15,15) is the inner corner of the L.
    assert _edge_type(faces, normals, vertices, (3, 9), neighbours[(3, 9)], 1.0) == "valley"
    assert _edge_type(faces, normals, vertices, (1, 7), neighbours[(1, 7)], 1.0) == "mountain"
    # Flipped outside reverses the answer.
    assert _edge_type(faces, normals, vertices, (3, 9), neighbours[(3, 9)], -1.0) == "mountain"
    assert _edge_type(faces, normals, vertices, (3, 9), neighbours[(3, 9)], None) == "fold"


def test_every_seam_number_is_printed_on_both_sides():
    net = unfold(parse_obj(CUBE_OBJ))
    labels = Counter(g["text"] for g in _graphics(net) if g["type"] == "text")
    assert set(labels) == {str(n) for n in range(1, net.stats["seams"] + 1)}
    assert set(labels.values()) == {2}


def test_printed_side_faces_outward():
    # Seen on the page (y grows downward), an outward counter-clockwise
    # triangle must still turn counter-clockwise, or the model comes out
    # mirrored with the print inside.
    net = unfold(parse_obj(CUBE_OBJ))
    assert net.stats["oriented"] is True
    faces = [g["points"] for g in _graphics(net)
             if g["type"] == "poly" and g["fill"] == "#e9dfcc"]
    for (ax, ay), (bx, by), (cx, cy) in faces:
        assert (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0


def test_inconsistent_winding_falls_back_to_plain_folds():
    flipped = CUBE_OBJ.replace(b"f 5 6 7 8", b"f 8 7 6 5")
    net = unfold(parse_obj(flipped))
    assert net.stats["oriented"] is False
    assert not any(g.get("fold_type") for g in _graphics(net))
    assert any("区別できません" in w for w in net.warnings)


def test_cylinder_side_unrolls_as_one_band():
    net = unfold(parse_obj(_cylinder_obj()))
    assert net.stats["islands"] == 1
    # 16 side quads joined by 15 folds, each cap on one fold, one side seam
    # and 15 cap seams per cap.
    assert net.stats["mountain_folds"] == 15 + 2
    assert net.stats["seams"] == 1 + 15 * 2


def test_svg_clip_window_stays_in_page_coordinates():
    net = unfold(parse_obj(CUBE_OBJ))
    spec = ModelSpec(name="cube", scale=1, template="box", width_m=0.05,
                     depth_m=0.05, height_m=0.05, roof="flat", pitch_deg=0)
    svg = render_svg(spec, 0, parts=net.parts)
    assert re.search(r'<g clip-path="url\(#piece0\)"><g transform="translate\(', svg)
    assert 'data-fold="mountain"' in svg
    assert 'data-layer="seam-number"' in svg
