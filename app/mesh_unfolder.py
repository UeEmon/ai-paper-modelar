"""Small, validated OBJ/STL mesh to paper-net islands.

The input has NO trustworthy unit metadata (especially STL). A user-specified
source unit and model scale establish physical millimetres. Supports TRIANGLES
only; OBJ polygon faces are fan-triangulated, which is appropriate for convex
planar polygons but not a general constrained triangulation.

This is deliberately bounded: no general high-poly mesh processing, arbitrary
free-form surface fitting, texture baking, or globally optimal net search.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import hypot, isfinite, sqrt
from struct import unpack_from
from typing import NamedTuple

from .net_engine import _part

MAX_MESH_BYTES = 5 * 1024 * 1024
MAX_VERTICES = 20000
MAX_FACES = 500
SOURCE_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
EPS = 1e-9


class MeshError(ValueError):
    def __init__(self, message: str, code: int = 422):
        super().__init__(message)
        self.code = code


class Mesh(NamedTuple):
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    source: str
    was_fan_triangulated: bool = False


@dataclass
class MeshNet:
    parts: list[dict]
    stats: dict
    warnings: list[str]


def _number(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MeshError("3Dモデルの座標値が不正です。") from exc
    if not isfinite(parsed) or abs(parsed) > 1e8:
        raise MeshError("NaN・無限大・極端な座標は使用できません。")
    return parsed


def _validate_mesh(mesh: Mesh) -> Mesh:
    if not mesh.vertices or not mesh.faces:
        raise MeshError("頂点または三角形のデータがありません。")
    if len(mesh.vertices) > MAX_VERTICES or len(mesh.faces) > MAX_FACES:
        raise MeshError("モデルが複雑すぎます。頂点20,000・三角形500以下へ簡略化してください。", 413)
    for face in mesh.faces:
        if len(set(face)) != 3 or any(i < 0 or i >= len(mesh.vertices) for i in face):
            raise MeshError("無効な三角形（頂点の重複・範囲外参照）があります。")
        a, b, c = (mesh.vertices[i] for i in face)
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cr = (u[1] * v[2] - u[2] * v[1],
              u[2] * v[0] - u[0] * v[2],
              u[0] * v[1] - u[1] * v[0])
        if sqrt(sum(t * t for t in cr)) <= 1e-11:
            raise MeshError("面積ゼロに近い三角形があります。メッシュを修復してください。")
    return mesh


def parse_obj(data: bytes) -> Mesh:
    try:
        content = data.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise MeshError("OBJはUTF-8文字コードで保存してください。", 415) from exc
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    fan = False
    for line in content.splitlines():
        tokens = line.strip().split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if tokens[0] == "v":
            if len(tokens) < 4:
                raise MeshError("OBJの頂点行が不正です。")
            vertices.append((_number(tokens[1]), _number(tokens[2]), _number(tokens[3])))
            if len(vertices) > MAX_VERTICES:
                raise MeshError("頂点が20,000を超えました。簡略化してください。", 413)
        elif tokens[0] == "f":
            if len(tokens) < 4:
                raise MeshError("OBJの面には3頂点以上が必要です。")
            indices = []
            for token in tokens[1:]:
                raw = token.split("/")[0]
                try:
                    idx = int(raw)
                except ValueError as exc:
                    raise MeshError("OBJの面の頂点番号が不正です。") from exc
                if idx == 0:
                    raise MeshError("OBJの頂点番号0は使用できません。")
                resolved = idx - 1 if idx > 0 else len(vertices) + idx
                if resolved < 0 or resolved >= len(vertices):
                    raise MeshError("OBJの面が定義されていない頂点を参照しています。")
                indices.append(resolved)
            if len(indices) > 3:
                fan = True
            for i in range(1, len(indices) - 1):
                faces.append((indices[0], indices[i], indices[i + 1]))
                if len(faces) > MAX_FACES:
                    raise MeshError("三角形が500を超えました。簡略化してください。", 413)
    return _validate_mesh(Mesh(vertices, faces, "OBJ", fan))


def parse_stl(data: bytes) -> Mesh:
    # Binary STL can begin with "solid", so detect it by an exact record length.
    binary = len(data) >= 84 and 84 + unpack_from("<I", data, 80)[0] * 50 == len(data)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    indexed: dict[tuple[float, float, float], int] = {}

    def add(pt):
        point = tuple(_number(str(value)) for value in pt)
        # STL has no vertex indexing. Welding is needed for shared topology.
        key = tuple(round(value, 7) for value in point)
        if key not in indexed:
            indexed[key] = len(vertices)
            vertices.append(point)
            if len(vertices) > MAX_VERTICES:
                raise MeshError("頂点が20,000を超えました。", 413)
        return indexed[key]

    if binary:
        count = unpack_from("<I", data, 80)[0]
        if count > MAX_FACES:
            raise MeshError("三角形が500を超えました。簡略化してください。", 413)
        for i in range(count):
            position = 84 + i * 50
            values = unpack_from("<12f", data, position)
            faces.append(tuple(add(values[3 + k * 3:6 + k * 3]) for k in range(3)))
    else:
        try:
            body = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise MeshError("STLを読み取れません。バイナリ/ASCII STLを確認してください。", 415) from exc
        group = []
        for line in body.splitlines():
            tokens = line.strip().split()
            if tokens and tokens[0].lower() == "vertex":
                if len(tokens) != 4:
                    raise MeshError("ASCII STLのvertex行が不正です。")
                group.append(add(tokens[1:]))
                if len(group) == 3:
                    faces.append(tuple(group))
                    group = []
                    if len(faces) > MAX_FACES:
                        raise MeshError("三角形が500を超えました。簡略化してください。", 413)
        if group:
            raise MeshError("ASCII STLの三角形データが不完全です。")
    return _validate_mesh(Mesh(vertices, faces, "STL"))


def load_mesh(data: bytes, filename: str) -> Mesh:
    if not data or len(data) > MAX_MESH_BYTES:
        raise MeshError("OBJ/STLファイルは5MB以内にしてください。", 413)
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "obj":
        return parse_obj(data)
    if suffix == "stl":
        return parse_stl(data)
    raise MeshError("対応形式はOBJとSTLだけです。", 415)


def _dist3(a, b):
    return sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _cross2(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _signed_area(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] -
               poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2


def _intersection_area(subject, clip):
    """Sutherland-Hodgman clipping of two convex triangle polygons."""
    polygon = list(subject)
    sign = 1 if _signed_area(clip) > 0 else -1
    for edge_idx in range(3):
        a, b = clip[edge_idx], clip[(edge_idx + 1) % 3]
        inp = polygon
        polygon = []
        if not inp:
            break
        prev = inp[-1]
        prev_dist = sign * _cross2(a, b, prev)
        for cur in inp:
            cur_dist = sign * _cross2(a, b, cur)
            if cur_dist >= -EPS:
                if prev_dist < -EPS:
                    alpha = prev_dist / (prev_dist - cur_dist)
                    polygon.append((
                        prev[0] + alpha * (cur[0] - prev[0]),
                        prev[1] + alpha * (cur[1] - prev[1]),
                    ))
                polygon.append(cur)
            elif prev_dist >= -EPS:
                alpha = prev_dist / (prev_dist - cur_dist)
                polygon.append((
                    prev[0] + alpha * (cur[0] - prev[0]),
                    prev[1] + alpha * (cur[1] - prev[1]),
                ))
            prev, prev_dist = cur, cur_dist
    return abs(_signed_area(polygon)) if len(polygon) >= 3 else 0.0


def _root(face, points):
    a, b, c = (points[i] for i in face)
    span = _dist3(a, b)
    ac = _dist3(a, c)
    bc = _dist3(b, c)
    x = (span * span + ac * ac - bc * bc) / (2 * span)
    y = sqrt(max(0, ac * ac - x * x))
    return {face[0]: (0., 0.), face[1]: (span, 0.), face[2]: (x, y)}


def _across(face, parent_face, parent_xy, points, common):
    """Flatten face across shared edge and put its third vertex on opposite side."""
    u, v = common
    w = next(i for i in face if i not in common)
    parent_w = next(i for i in parent_face if i not in common)
    p, q = parent_xy[u], parent_xy[v]
    span = hypot(q[0] - p[0], q[1] - p[1])
    d0, d1 = _dist3(points[u], points[w]), _dist3(points[v], points[w])
    x = (span * span + d0 * d0 - d1 * d1) / (2 * span)
    y = sqrt(max(0, d0 * d0 - x * x))
    ux, uy = (q[0] - p[0]) / span, (q[1] - p[1]) / span
    parent_side = _cross2(p, q, parent_xy[parent_w])
    orient = -1 if parent_side > 0 else 1
    new = (p[0] + ux * x - uy * y * orient,
           p[1] + uy * x + ux * y * orient)
    return {u: p, v: q, w: new}


def _geom_line(p, q, kind, color="#333333"):
    return {"type": "line", "x1": p[0], "y1": p[1],
            "x2": q[0], "y2": q[1],
            "kind": kind, "stroke": color}


def _geom_poly(pts, color, *, stroke="none", kind="detail"):
    return {"type": "poly", "points": list(pts), "kind": kind,
            "fill": color, "stroke": stroke}


def _tab_coords(p, q, third):
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = hypot(dx, dy)
    if length < 0.8:
        return None
    u = (dx / length, dy / length)
    sign = -1 if _cross2(p, q, third) > 0 else 1
    normal = (-u[1] * sign, u[0] * sign)
    inset = min(1.2, length * .12)
    depth = min(4.0, length * .24)
    a = (p[0] + u[0] * inset, p[1] + u[1] * inset)
    b = (q[0] - u[0] * inset, q[1] - u[1] * inset)
    return [p, a,
            (a[0] + normal[0] * depth, a[1] + normal[1] * depth),
            (b[0] + normal[0] * depth, b[1] + normal[1] * depth),
            b, q]


def unfold(mesh: Mesh, *, unit: str = "mm", scale: int = 1,
           glue_tabs: bool = True, color: str = "#e9dfcc") -> MeshNet:
    if unit not in SOURCE_UNITS:
        raise MeshError("OBJ/STLの元寸法単位をmm・cm・mから選択してください。")
    if not isinstance(scale, int) or not 1 <= scale <= 500:
        raise MeshError("縮尺は1/1〜1/500を指定してください。")
    factor = SOURCE_UNITS[unit] / scale
    raw = mesh.vertices
    minimum = tuple(min(v[i] for v in raw) for i in range(3))
    points = [tuple((v[i] - minimum[i]) * factor for i in range(3))
              for v in raw]
    dimensions = [max(v[i] for v in points) for i in range(3)]
    if max(dimensions) < 0.5:
        raise MeshError("変換後のモデルが小さすぎます（最大寸法0.5mm未満）。")
    # Detect edges with more than two adjacent triangles. A manifold solid has
    # at most two triangles per undirected edge, regardless of winding.
    neighbors = defaultdict(list)
    for fi, face in enumerate(mesh.faces):
        for k in range(3):
            edge = tuple(sorted((face[k], face[(k + 1) % 3])))
            neighbors[edge].append(fi)
            if len(neighbors[edge]) > 2:
                raise MeshError("3面以上が共有する辺があります。非多様体メッシュを修復してください。")
    open_edges = sum(len(indices) == 1 for indices in neighbors.values())
    placed_faces = set()
    forest = []
    refused = 0
    fold_edges = set()

    # Start a fresh island for any triangle whose overlap-free connection is
    # unavailable. This guarantees every input triangle is represented.
    while len(placed_faces) < len(mesh.faces):
        root_id = next(i for i in range(len(mesh.faces)) if i not in placed_faces)
        coordinates = {root_id: _root(mesh.faces[root_id], points)}
        placed_faces.add(root_id)
        queue = deque([root_id])
        folds = set()
        while queue:
            parent = queue.popleft()
            pface = mesh.faces[parent]
            for k in range(3):
                edge = tuple(sorted((pface[k], pface[(k + 1) % 3])))
                adjacent = neighbors[edge]
                if len(adjacent) != 2:
                    continue
                nxt = adjacent[0] if adjacent[1] == parent else adjacent[1]
                if nxt in placed_faces:
                    continue
                triangle = _across(mesh.faces[nxt], pface,
                                   coordinates[parent], points, edge)
                coords = [triangle[index] for index in mesh.faces[nxt]]
                # Use strict positive-area overlap, allowing shared edges.
                if any(_intersection_area(coords,
                       [existing[index] for index in mesh.faces[other]]) > 1e-5
                       for other, existing in coordinates.items()):
                    refused += 1
                    continue
                coordinates[nxt] = triangle
                placed_faces.add(nxt)
                queue.append(nxt)
                folds.add(edge)
                fold_edges.add(edge)
        forest.append((coordinates, folds))

    parts = []
    seam_edges = 0
    tab_count = 0
    for piece_idx, (coordinates, folds) in enumerate(forest, 1):
        graphics = []
        for fi, mapping in coordinates.items():
            triangle = [mapping[i] for i in mesh.faces[fi]]
            graphics.append(_geom_poly(triangle, color))
        for fi, mapping in coordinates.items():
            face = mesh.faces[fi]
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                edge = tuple(sorted((a, b)))
                p, q = mapping[a], mapping[b]
                third = mapping[face[(k + 2) % 3]]
                if edge in folds:
                    if fi == min(neighbors[edge]):
                        graphics.append(_geom_line(p, q, "fold"))
                    continue
                # Shared edges not selected as folds become cut-and-glue seams.
                shared = len(neighbors[edge]) == 2
                tab_side = fi == min(neighbors[edge])
                if shared and tab_side and glue_tabs:
                    polygon = _tab_coords(p, q, third)
                    if polygon is not None:
                        quad = polygon[1:5]
                        if not any(_intersection_area(
                              [quad[0], quad[1], quad[2]],
                              [coords[v] for v in mesh.faces[j]]) > 1e-5 or
                              _intersection_area(
                              [quad[0], quad[2], quad[3]],
                              [coords[v] for v in mesh.faces[j]]) > 1e-5
                              for j, coords in coordinates.items() if j != fi):
                            graphics.append(_geom_poly(polygon, "#f1e5cb"))
                            for u, v in zip(polygon[:-1], polygon[1:]):
                                graphics.append(_geom_line(u, v, "cut"))
                            graphics.append(_geom_line(p, q, "fold"))
                            tab_count += 1
                            seam_edges += 1
                            continue
                graphics.append(_geom_line(p, q, "cut"))
                if shared:
                    seam_edges += 1
        parts.append(_part("Mesh island " + str(piece_idx), graphics))
    warnings = [
        "OBJ/STLの座標には単位が含まれない場合があります。元単位と縮尺を確認してください。",
        "面の重なりを避けるため複数の展開島に分割する場合があります。",
        "折り方向の山折り・谷折り、紙厚、切り代、物理的な組立品質は未検証です。",
    ]
    if open_edges:
        warnings.append("境界辺{}本：閉じていないメッシュです。底面や開口が残る可能性があります。".format(open_edges))
    if mesh.was_fan_triangulated:
        warnings.append("OBJの多角形を扇型三角分割しました。凹面は予め三角形化してください。")
    if refused:
        warnings.append("配置衝突により{}回の接続候補を分離しました。".format(refused))
    return MeshNet(
        parts=parts,
        stats={
            "format": mesh.source, "vertices": len(mesh.vertices),
            "triangles": len(mesh.faces), "islands": len(parts),
            "folds": len(fold_edges), "tabs": tab_count,
            "open_edges": open_edges,
            "size_mm": [round(d, 3) for d in dimensions],
        },
        warnings=warnings,
    )
