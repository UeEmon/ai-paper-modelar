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
from random import Random
from math import atan2, cos, floor, hypot, isfinite, sin, sqrt
from struct import unpack_from
from typing import NamedTuple

from .net_engine import _part

MAX_MESH_BYTES = 5 * 1024 * 1024
MAX_VERTICES = 20000
MAX_FACES = 3000
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
        raise MeshError("モデルが複雑すぎます。頂点20,000・三角形3,000以下へ簡略化してください。", 413)
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
                    raise MeshError("三角形が3,000を超えました。簡略化してください。", 413)
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
            raise MeshError("三角形が3,000を超えました。簡略化してください。", 413)
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
                        raise MeshError("三角形が3,000を超えました。簡略化してください。", 413)
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


# A piece must fit the printable area of one A4 sheet (186 x 225 mm, less the
# 6 mm border on each side) with room left for glue tabs around it.
ISLAND_MAX_LONG = 205.0
ISLAND_MAX_SHORT = 166.0


class _Grid:
    """Uniform grid of triangles, so an overlap test looks only nearby."""

    def __init__(self, cell: float):
        self.cell = cell
        self.cells = defaultdict(list)
        self.shapes = {}

    def _keys(self, pts):
        c = self.cell
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        for i in range(floor(min(xs) / c), floor(max(xs) / c) + 1):
            for j in range(floor(min(ys) / c), floor(max(ys) / c) + 1):
                yield (i, j)

    def add(self, key, triangle):
        self.shapes[key] = triangle
        for cell in self._keys(triangle):
            self.cells[cell].append(key)

    def hits(self, polygon, ignore=None) -> bool:
        seen = set()
        for cell in self._keys(polygon):
            for key in self.cells.get(cell, ()):
                if key in seen or key == ignore:
                    continue
                seen.add(key)
                if _intersection_area(polygon, self.shapes[key]) > 1e-5:
                    return True
        return False


class _Island:
    def __init__(self, cell: float):
        self.coords = {}
        self.folds = set()
        self.grid = _Grid(cell)
        self.bbox = None

    def fits_with(self, pts) -> bool:
        x0, y0, x1, y1 = self.bbox
        x0 = min([x0] + [p[0] for p in pts])
        x1 = max([x1] + [p[0] for p in pts])
        y0 = min([y0] + [p[1] for p in pts])
        y1 = max([y1] + [p[1] for p in pts])
        w, h = x1 - x0, y1 - y0
        return max(w, h) <= ISLAND_MAX_LONG and min(w, h) <= ISLAND_MAX_SHORT

    def add(self, fi, mapping, faces):
        triangle = [mapping[v] for v in faces[fi]]
        self.coords[fi] = mapping
        self.grid.add(fi, triangle)
        xs = [p[0] for p in triangle]
        ys = [p[1] for p in triangle]
        if self.bbox is None:
            self.bbox = (min(xs), min(ys), max(xs), max(ys))
        else:
            x0, y0, x1, y1 = self.bbox
            self.bbox = (min([x0] + xs), min([y0] + ys),
                         max([x1] + xs), max([y1] + ys))


def _grow(faces, points, neighbors, bend, cell, order):
    """Unfold every triangle into islands, growing each from a root along the
    gentlest bends. A triangle that would overlap its island, or make it too
    large for one sheet, is left for another island."""
    placed_faces = set()
    islands = []
    refused = 0
    too_big = 0
    counter = 0
    roots = iter(order)
    while len(placed_faces) < len(faces):
        root_id = next(i for i in roots if i not in placed_faces)
        island = _Island(cell)
        island.add(root_id, _root(faces[root_id], points), faces)
        placed_faces.add(root_id)
        heap = []

        def push(parent):
            nonlocal counter
            pface = faces[parent]
            for k in range(3):
                edge = tuple(sorted((pface[k], pface[(k + 1) % 3])))
                adjacent = neighbors[edge]
                if len(adjacent) != 2:
                    continue
                nxt = adjacent[0] if adjacent[1] == parent else adjacent[1]
                if nxt in placed_faces:
                    continue
                counter += 1
                heappush(heap, (bend(edge), counter, parent, nxt, edge))

        push(root_id)
        while heap:
            _, _, parent, nxt, edge = heappop(heap)
            if nxt in placed_faces:
                continue
            triangle = _across(faces[nxt], faces[parent],
                               island.coords[parent], points, edge)
            coords = [triangle[index] for index in faces[nxt]]
            if not island.fits_with(coords):
                too_big += 1
                continue
            # Use strict positive-area overlap, allowing shared edges.
            if island.grid.hits(coords):
                refused += 1
                continue
            island.add(nxt, triangle, faces)
            placed_faces.add(nxt)
            island.folds.add(edge)
            push(nxt)
        islands.append(island)
    return islands, refused, too_big


def _merge_islands(islands, faces, neighbors, bend) -> int:
    """Glue small pieces onto a neighbouring piece where they fit without
    overlapping, smallest first, turning the seam between them into a fold."""
    owner = {fi: island for island in islands for fi in island.coords}
    merged = 0
    changed = True
    while changed:
        changed = False
        for small in sorted((i for i in islands if i.coords), key=lambda i: len(i.coords)):
            if not small.coords:
                continue
            candidates = []
            for fi in small.coords:
                face = faces[fi]
                for k in range(3):
                    edge = tuple(sorted((face[k], face[(k + 1) % 3])))
                    if len(neighbors[edge]) != 2:
                        continue
                    other = neighbors[edge][0] if neighbors[edge][1] == fi else neighbors[edge][1]
                    if owner[other] is not small:
                        candidates.append((bend(edge), edge, fi, other))
            candidates.sort(key=lambda c: c[0])
            for _, edge, fi, other in candidates:
                big = owner[other]
                moved = _attach(small, big, edge, fi, other, faces)
                if moved is None:
                    continue
                for face_id, mapping in moved.items():
                    big.add(face_id, mapping, faces)
                    owner[face_id] = big
                big.folds |= small.folds | {edge}
                small.coords = {}
                merged += 1
                changed = True
                break
    return merged


def _attach(small, big, edge, fi, other, faces):
    """small moved rigidly so its edge meets big's copy, or None if it would
    flip over, overlap big, or make big too large for one sheet."""
    u, v = edge
    p, q = small.coords[fi][u], small.coords[fi][v]
    P, Q = big.coords[other][u], big.coords[other][v]
    turn = atan2(Q[1] - P[1], Q[0] - P[0]) - atan2(q[1] - p[1], q[0] - p[0])
    c, s = cos(turn), sin(turn)

    def move(point):
        x, y = point[0] - p[0], point[1] - p[1]
        return (P[0] + c * x - s * y, P[1] + s * x + c * y)

    third_small = move(small.coords[fi][next(i for i in faces[fi] if i not in edge)])
    third_big = big.coords[other][next(i for i in faces[other] if i not in edge)]
    if _cross2(P, Q, third_small) * _cross2(P, Q, third_big) >= 0:
        return None
    moved = {face_id: {vertex: move(xy) for vertex, xy in mapping.items()}
             for face_id, mapping in small.coords.items()}
    every = [xy for mapping in moved.values() for xy in mapping.values()]
    if not big.fits_with(every):
        return None
    for face_id, mapping in moved.items():
        if big.grid.hits([mapping[vertex] for vertex in faces[face_id]]):
            return None
    return moved


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

    lengths = [_dist3(points[e[0]], points[e[1]]) for e in neighbors]
    cell = max(1.0, sum(lengths) / len(lengths))
    def bend(edge):
        """Gentlest bends first: flat joins, then shallow folds, so a flat
        polygon stays whole and a curved band (a cylinder side) one strip."""
        a, b = neighbors[edge]
        return 0. if edge_type[edge] == "flat" else 1. - _dot(normals[a], normals[b])

    # Where the unfolding starts changes how many pieces it ends in (a torus
    # can come out in 2 pieces or 15), so try a few starts and keep the one
    # with the fewest pieces. Bigger meshes get fewer tries to bound the time.
    tries = min(8, max(2, 12000 // len(mesh.faces)))
    best = None
    for attempt in range(tries):
        order = list(range(len(mesh.faces)))
        if attempt:
            Random(attempt).shuffle(order)
        result = _grow(mesh.faces, points, neighbors, bend, cell, order)
        score = (len(result[0]), result[1] + result[2])
        if best is None or score < best[0]:
            best = (score, result)
    islands, refused, too_big = best[1]

    merged = _merge_islands(islands, mesh.faces, neighbors, bend)
    islands = [island for island in islands if island.coords]
    fold_edges = set().union(*(island.folds for island in islands))

    # _root/_across keep the triangle winding, so the page shows the model
    # from inside when triangles wind counter-clockwise outward. Mirror then,
    # so the printed side ends up outside and the model is not mirrored.
    # Each island is also turned so its long side runs down the page.
    mirror = oriented and outward > 0
    forest = []
    for island in islands:
        width = island.bbox[2] - island.bbox[0]
        height = island.bbox[3] - island.bbox[1]
        turn = width > height

        def place(point, mirror=mirror, turn=turn):
            x, y = point
            if mirror:
                y = -y
            return (-y, x) if turn else (x, y)
        forest.append(({fi: {v: place(xy) for v, xy in mapping.items()}
                        for fi, mapping in island.coords.items()}, island.folds))

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
        grid = _Grid(cell)
        for fi, mapping in coordinates.items():
            triangle = [mapping[i] for i in mesh.faces[fi]]
            grid.add(fi, triangle)
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
                        halves = ([quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]])
                        # Neither on a face of this piece nor on another tab.
                        if not any(grid.hits(half, ignore=fi) for half in halves):
                            for k_half, half in enumerate(halves):
                                grid.add(("tab", tab_count, k_half), half)
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
    if too_big:
        warnings.append("1枚の用紙（A4）に収まるよう、大きな部品を分けました。")
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
            "merged_islands": merged,
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
