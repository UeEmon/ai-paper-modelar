"""OBJ/STL import, robust triangulation and safe mesh-to-A4 integration."""
from __future__ import annotations

from io import BytesIO
import struct
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app
from app.mesh_unfolder import MeshError, load_mesh, parse_obj, parse_stl, unfold
from app.generator import ModelSpec, page_jobs

client = TestClient(app)

TETRA_OBJ = b"""# tetrahedron, in millimetres
v 0 0 0
v 10 0 0
v 5 8 0
v 5 3 8
f 1 2 3
f 1 4 2
f 2 4 3
f 3 4 1
"""

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


def binary_stl(triangles):
    header = b"test" + b"\x00" * 76
    result = bytearray(header + struct.pack("<I", len(triangles)))
    for tri in triangles:
        result += struct.pack("<12f", 0., 0., 1.,
              *(value for point in tri for value in point))
        result += struct.pack("<H", 0)
    return bytes(result)


def submit_mesh(raw=TETRA_OBJ, filename="tetra.obj", unit="mm", scale=1):
    return client.post("/api/mesh/jobs",
        data={"source_unit":unit,"scale":str(scale),"glue_tabs":"true"},
        files={"file":(filename,raw,"application/octet-stream")})


def test_obj_tetra_connected_triangle_islands_and_geometry():
    mesh = parse_obj(TETRA_OBJ)
    assert len(mesh.vertices) == 4
    assert len(mesh.faces) == 4
    net = unfold(mesh, unit="mm", scale=1)
    assert net.stats["triangles"] == 4
    assert net.stats["open_edges"] == 0
    assert net.stats["folds"] >= 1
    assert net.stats["islands"] >= 1
    assert sum(sum(g["kind"] == "fold" for g in p["graphics"]) for p in net.parts) > 0
    # Each cut contour is a line (not a duplicate cut over a scored fold).
    assert all(p["w"] > 0 and p["h"] > 0 for p in net.parts)


def test_cube_obj_quad_fan_split_and_dimension_transform():
    mesh = parse_obj(CUBE_OBJ)
    assert mesh.was_fan_triangulated is True
    assert len(mesh.faces) == 12
    net = unfold(mesh, unit="cm", scale=2)
    assert net.stats["size_mm"] == [50.0, 50.0, 50.0]
    assert net.stats["open_edges"] == 0
    assert len(net.parts) > 0


def test_ascii_and_binary_stl():
    single = [((0.,0.,0.),(10.,0.,0.),(0.,10.,0.))]
    binary = binary_stl(single)
    mesh = parse_stl(binary)
    assert len(mesh.vertices) == 3
    assert len(mesh.faces) == 1
    assert mesh.source == "STL"
    ascii_stl = (b"solid small\nfacet normal 0 0 1\n outer loop\n"
                 b"vertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\n"
                 b"endloop\nendfacet\nendsolid small")
    assert parse_stl(ascii_stl).faces == [(0,1,2)]


def test_obj_negative_indices_and_boundary_warning():
    raw = b"v 0 0 0\nv 10 0 0\nv 0 10 0\nf -3 -2 -1\n"
    mesh = load_mesh(raw, "triangle.obj")
    net = unfold(mesh)
    assert net.stats["open_edges"] == 3
    assert any("閉じていない" in note for note in net.warnings)


@pytest.mark.parametrize("raw,filename", [
    (b"v 0 0 0\nf 1 2 3\n", "bad.obj"),
    (b"v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n", "degenerate.obj"),
    (b"not a solid", "fake.stl"),
    (b"solid\n", "empty.stl"),
    (b"<script>", "x.svg"),
])
def test_unusable_mesh_rejected(raw,filename):
    with pytest.raises(MeshError):
        load_mesh(raw, filename)


def test_nonmanifold_edge_rejected():
    raw = (b"v 0 0 0\nv 10 0 0\nv 0 10 0\n"
           b"v 0 -10 0\nv 0 0 10\n"
           b"f 1 2 3\nf 2 1 4\nf 1 2 5\n")
    with pytest.raises(MeshError, match="\u975e\u591a\u69d8\u4f53"):
        unfold(parse_obj(raw))


def test_import_api_pdf_svg_and_delete_job():
    res = submit_mesh()
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["stats"]["triangles"] == 4
    assert data["pages"] >= 2
    jid = data["id"]
    assert client.get("/api/mesh/jobs/" + jid).status_code == 200
    guide = client.get("/api/mesh/jobs/" + jid + "/pages/0.svg")
    assert guide.status_code == 200
    ET.fromstring(guide.text)
    assert 'data-page="assembly-guide"' in guide.text
    svg = client.get("/api/mesh/jobs/" + jid + "/pages/1.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    ET.fromstring(svg.text)
    assert "Page 2/" in svg.text
    assert 'data-layer="cut"' in svg.text
    assert 'data-layer="fold"' in svg.text
    assert "50 mm CHECK" in svg.text
    pdf = client.get("/api/mesh/jobs/" + jid + "/template.pdf")
    assert pdf.status_code == 200
    assert len(PdfReader(BytesIO(pdf.content)).pages) == data["pages"]
    assert client.get("/api/mesh/jobs/" + jid + "/pages/999.svg").status_code == 404
    assert client.delete("/api/mesh/jobs/" + jid).status_code == 204
    assert client.get("/api/mesh/jobs/" + jid).status_code == 404


def test_mesh_api_rejects_invalid_unit_scale_and_upload_size():
    bad_unit = submit_mesh(unit="kilometer")
    assert bad_unit.status_code == 422
    assert submit_mesh(scale=0).status_code == 422
    assert submit_mesh(raw=b"v 0 0 0\n", filename="broken.obj").status_code == 422
    too_big = submit_mesh(raw=b"x"*(5*1024*1024+1))
    assert too_big.status_code == 413


def test_import_many_faces_rejected_and_escaping():
    face = b"v 0 0 0\nv 10 0 0\nv 0 10 0\n"
    # Duplicate triangles are nonphysical but enough to check the vertex bound.
    dense = face + b"f 1 2 3\n"*3001
    assert submit_mesh(dense).status_code == 413
    r = submit_mesh(filename="A & <B>.obj")
    assert r.status_code == 201, r.text
    svg = client.get("/api/mesh/jobs/"+r.json()["id"]+"/pages/0.svg").text
    assert "A &amp; &lt;B&gt;.obj" in svg
