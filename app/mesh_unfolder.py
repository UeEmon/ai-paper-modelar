"""Small, validated OBJ/STL mesh to paper-net islands.

The input has NO trustworthy unit metadata (especially STL). A user-specified
source unit and model scale establish physical millimetres. Supports TRIANGLES
only; OBJ polygon faces are fan-triangulated, which is appropriate for convex
planar polygons but not a general constrained triangulation.

This is deliberately bounded: no general high-poly mesh processing, arbitrary
free-form surface fitting, texture baking, or globally optimal net search.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush
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


FLAT_COS = 0.99995  # about 0.6 degrees between neighbouring normals


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normal(face, points):
    a, b, c = (points[i] for i in face)
    n = _cross3(_sub3(b, a), _sub3(c, a))
    length = sqrt(_dot(n, n))
    return (n[0] / length, n[1] / length, n[2] / length) if length > EPS else (0., 0., 0.)


def _opposite_winding(face_a, face_b, edge):
    """True when the two triangles walk their shared edge in opposite directions."""
    def direction(face):
        for k in range(3):
            if (face[k], face[(k + 1) % 3]) == edge:
                return 1
            if (face[(k + 1) % 3], face[k]) == edge:
                return -1
        return 0
    return direction(face_a) * direction(face_b) == -1


def _edge_type(faces, normals, points, edge, adjacent, outward):
    """flat, mountain or valley (seen from the printed outside), or fold if unknown."""
    a, b = adjacent
    if abs(_dot(normals[a], normals[b])) >= FLAT_COS:
        return "flat"
    if outward is None:
        return "fold"
    other = next(i for i in faces[b] if i not in edge)
    n = normals[a]
    height = _dot((n[0] * outward, n[1] * outward, n[2] * outward),
                  _sub3(points[other], points[edge[0]]))
    return "mountain" if height < 0 else "valley"


def _seam_label(p, q, third, number):
    """Edge number printed just inside the face, centred on the edge."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = hypot(dx, dy)
    if length < 1.5:
        return None
    inward = abs(_cross2(p, q, third)) / length
    size = max(1.2, min(2.8, length * .3, inward * .45))
    sign = 1 if _cross2(p, q, third) > 0 else -1
    nx, ny = -dy / length * sign, dx / length * sign
    offset = min(size * .9, inward * .4)
    return {"type": "text", "x": (p[0] + q[0]) / 2 + nx * offset,
            "y": (p[1] + q[1]) / 2 + ny * offset, "text": str(number),
            "size": round(size, 2), "kind": "detail", "fill": "#7a2e1f",
            "stroke": "none"}


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
    normals = [_normal(face, points) for face in mesh.faces]
    # Mountain/valley folds need a trustworthy outside. Only a closed mesh
    # whose triangles all wind the same way gives one.
    consistent = all(_opposite_winding(mesh.faces[a], mesh.faces[b], edge)
                     for edge, (a, b) in ((e, f) for e, f in neighbors.items()
                                          if len(f) == 2))
    oriented = consistent and not open_edges
    volume = sum(_dot(points[f[0]], _cross3(points[f[1]], points[f[2]]))
                 for f in mesh.faces)
    outward = 1.0 if volume >= 0 else -1.0
    edge_type = {}
    for edge, adjacent in neighbors.items():
        if len(adjacent) == 2:
            edge_type[edge] = _edge_type(mesh.faces, normals, points, edge,
                                         adjacent, outward if oriented else None)

    placed_faces = set()
    forest = []
    refused = 0
    fold_edges = set()
    counter = 0

    # Start a fresh island for any triangle whose overlap-free connection is
    # unavailable. This guarantees every input triangle is represented.
    # Edges inside a flat face are joined first, so a flat polygon stays in
    # one piece without fold lines across it.
    while len(placed_faces) < len(mesh.faces):
        root_id = next(i for i in range(len(mesh.faces)) if i not in placed_faces)
        coordinates = {root_id: _root(mesh.faces[root_id], points)}
        placed_faces.add(root_id)
        heap = []
        folds = set()

        def push(parent):
            nonlocal counter
            pface = mesh.faces[parent]
            for k in range(3):
                edge = tuple(sorted((pface[k], pface[(k + 1) % 3])))
                adjacent = neighbors[edge]
                if len(adjacent) != 2:
                    continue
                nxt = adjacent[0] if adjacent[1] == parent else adjacent[1]
                if nxt in placed_faces:
                    continue
                counter += 1
                # Gentlest bends first: flat joins, then shallow folds, so a
                # curved band (a cylinder side) stays one strip.
                a, b = adjacent
                priority = 0. if edge_type[edge] == "flat" else \
                    1. - _dot(normals[a], normals[b])
                heappush(heap, (priority, counter, parent, nxt, edge))

        push(root_id)
        while heap:
            _, _, parent, nxt, edge = heappop(heap)
            if nxt in placed_faces:
                continue
            pface = mesh.faces[parent]
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
            folds.add(edge)
            fold_edges.add(edge)
            push(nxt)
        forest.append((coordinates, folds))

    # _root/_across keep the triangle winding, so the page shows the model
    # from inside when triangles wind counter-clockwise outward. Mirror then,
    # so the printed side ends up outside and the model is not mirrored.
    if oriented and outward > 0:
        forest = [({fi: {v: (x, -y) for v, (x, y) in mapping.items()}
                    for fi, mapping in coordinates.items()}, folds)
                  for coordinates, folds in forest]

    seam_numbers = {}
    for coordinates, folds in forest:
        for fi in coordinates:
            face = mesh.faces[fi]
            for k in range(3):
                edge = tuple(sorted((face[k], face[(k + 1) % 3])))
                if (len(neighbors[edge]) == 2 and edge not in folds
                        and edge not in seam_numbers):
                    seam_numbers[edge] = len(seam_numbers) + 1

    parts = []
    seam_edges = 0
    tab_count = 0
    hidden_flat = 0
    fold_counts = {"mountain": 0, "valley": 0}
    for piece_idx, (coordinates, folds) in enumerate(forest, 1):
        graphics = []
        labels = []
        for fi, mapping in coordinates.items():
            triangle = [mapping[i] for i in mesh.faces[fi]]
            # Outline each triangle in its own colour so no hairline gap
            # shows between neighbouring triangles of a flat face.
            graphics.append(_geom_poly(triangle, color, stroke=color))
        for fi, mapping in coordinates.items():
            face = mesh.faces[fi]
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                edge = tuple(sorted((a, b)))
                p, q = mapping[a], mapping[b]
                third = mapping[face[(k + 2) % 3]]
                if edge in folds:
                    if fi == min(neighbors[edge]):
                        kind = edge_type[edge]
                        if kind == "flat":
                            hidden_flat += 1
                        else:
                            line = _geom_line(p, q, "fold")
                            if kind in fold_counts:
                                line["fold_type"] = kind
                                fold_counts[kind] += 1
                            graphics.append(line)
                    continue
                # Shared edges not selected as folds become cut-and-glue seams.
                shared = len(neighbors[edge]) == 2
                if shared:
                    label = _seam_label(p, q, third, seam_numbers[edge])
                    if label is not None:
                        labels.append(label)
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
                            tab_fold = _geom_line(p, q, "fold")
                            if oriented:
                                # Tabs fold behind the printed side.
                                tab_fold["fold_type"] = "mountain"
                            graphics.append(tab_fold)
                            tab_count += 1
                            seam_edges += 1
                            continue
                graphics.append(_geom_line(p, q, "cut"))
                if shared:
                    seam_edges += 1
        parts.append(_part("Mesh island " + str(piece_idx), graphics + labels))
    warnings = [
        "OBJ/STLの座標には単位が含まれない場合があります。元単位と縮尺を確認してください。",
        "面の重なりを避けるため複数の展開島に分割する場合があります。",
        "切り離した辺には両側に同じ番号を印刷しています。同じ番号どうしを貼り合わせてください。",
    ]
    if oriented:
        warnings.append("印刷面が外側になる向きで展開しました。一点鎖線は山折り、破線は谷折りです。"
                        "紙厚・切り代は補正していません。")
    else:
        warnings.append("閉じていない、または面の向きがそろっていないメッシュのため、"
                        "山折り・谷折りを区別できません（折り線はすべて破線）。")
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
            "mountain_folds": fold_counts["mountain"],
            "valley_folds": fold_counts["valley"],
            "flat_edges_hidden": hidden_flat,
            "seams": len(seam_numbers), "oriented": oriented,
            "open_edges": open_edges,
            "size_mm": [round(d, 3) for d in dimensions],
        },
        warnings=warnings,
    )


def thumbnail(mesh: Mesh) -> bytes:
    """Small isometric diagnostic preview, not a faithful rendered material."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    width, height = 360, 260
    image = Image.new("RGB", (width, height), "#fcfcf9")
    painter = ImageDraw.Draw(image)
    coords = []
    for x, y, z in mesh.vertices:
        coords.append((x - y, (x + y) * 0.43 - z * 1.20))
    lo_x, hi_x = min(p[0] for p in coords), max(p[0] for p in coords)
    lo_y, hi_y = min(p[1] for p in coords), max(p[1] for p in coords)
    scale = min(300 / max(1e-9, hi_x - lo_x),
                205 / max(1e-9, hi_y - lo_y))
    midx = (hi_x + lo_x) / 2
    midy = (hi_y + lo_y) / 2
    drawing = [
        (180 + (x - midx) * scale, 123 + (y - midy) * scale)
        for x, y in coords
    ]
    depth = lambda face: sum(
        mesh.vertices[i][0] + mesh.vertices[i][1] + mesh.vertices[i][2]
        for i in face) / 3
    for face in sorted(mesh.faces, key=depth):
        painter.polygon([drawing[i] for i in face],
                        fill="#e7dfce", outline="#4b675d", width=1)
    painter.text((12, 236), mesh.source + "  /  " + str(len(mesh.faces)) +
                 " triangles", fill="#344b42")
    out = BytesIO()
    image.save(out, format="JPEG", quality=82)
    return out.getvalue()
