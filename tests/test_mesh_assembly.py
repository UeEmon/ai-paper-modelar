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


def _sphere_obj(around=32, down=24, radius=30.0):
    vertices = [(0, 0, radius)]
    for i in range(1, down):
        t = pi * i / down
        for j in range(around):
            a = 2 * pi * j / around
            vertices.append((radius * sin(t) * cos(a), radius * sin(t) * sin(a),
                             radius * cos(t)))
    vertices.append((0, 0, -radius))
    faces = [(1, 2 + j, 2 + (j + 1) % around) for j in range(around)]
    for i in range(down - 2):
        a, b = 2 + i * around, 2 + (i + 1) * around
        for j in range(around):
            k = (j + 1) % around
            faces += [(a + j, b + j, b + k), (a + j, b + k, a + k)]
    last, a = len(vertices), 2 + (down - 2) * around
    faces += [(a + j, last, a + (j + 1) % around) for j in range(around)]
    return _obj(vertices, faces)


def test_large_model_pieces_each_fit_one_sheet():
    # A 160 mm ball does not fit one A4 sheet as one piece.
    net = unfold(parse_obj(_sphere_obj(radius=80.0)))
    assert net.stats["triangles"] == 1472
    assert net.stats["islands"] > 1
    spec = ModelSpec(name="ball", scale=1, template="box", width_m=0.05,
                     depth_m=0.05, height_m=0.05, roof="flat", pitch_deg=0)
    from app.generator import page_jobs
    for page in page_jobs(spec, net.parts):
        for place in page["placements"]:
            assert place["tile"] == (1, 1, 1, 1)
    assert any("1枚の用紙" in w for w in net.warnings)


def test_glue_tabs_never_overlap_faces_or_each_other():
    from app.mesh_unfolder import _intersection_area
    net = unfold(parse_obj(_sphere_obj(around=16, down=12)))
    for part in net.parts:
        faces = [g["points"] for g in part["graphics"]
                 if g["type"] == "poly" and g["fill"] == "#e9dfcc"]
        tabs = [g["points"][1:5] for g in part["graphics"]
                if g["type"] == "poly" and g["fill"] == "#f1e5cb"]
        halves = [h for q in tabs for h in ([q[0], q[1], q[2]], [q[0], q[2], q[3]])]
        for i, half in enumerate(halves):
            for face in faces:
                assert _intersection_area(half, face) < 1e-4
            for j, other in enumerate(halves):
                if i // 2 != j // 2:
                    assert _intersection_area(half, other) < 1e-4


def test_small_pieces_are_merged_into_neighbours():
    from app import mesh_unfolder as engine
    mesh = parse_obj(CUBE_OBJ)
    points = [tuple(float(c) for c in v) for v in mesh.vertices]
    neighbours = defaultdict(list)
    for index, face in enumerate(mesh.faces):
        for k in range(3):
            neighbours[tuple(sorted((face[k], face[(k + 1) % 3])))].append(index)
    saved = engine.ISLAND_MAX_LONG, engine.ISLAND_MAX_SHORT
    try:
        # Force one piece per square, then let them join again.
        engine.ISLAND_MAX_LONG = engine.ISLAND_MAX_SHORT = 10.5
        islands, _, _ = engine._grow(mesh.faces, points, neighbours,
                                     lambda edge: 0., 10., list(range(12)))
        assert len(islands) == 6
    finally:
        engine.ISLAND_MAX_LONG, engine.ISLAND_MAX_SHORT = saved
    assert engine._merge_islands(islands, mesh.faces, neighbours, lambda edge: 0.) == 5
    assert len([island for island in islands if island.coords]) == 1


def test_three_thousand_triangles_are_accepted():
    mesh = parse_obj(_sphere_obj(around=48, down=32))
    assert len(mesh.faces) == 2976
    net = unfold(mesh)
    assert net.stats["triangles"] == 2976
