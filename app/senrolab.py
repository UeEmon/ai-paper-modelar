"""SenroLab 連携: 仮オブジェクト1個の展開図（実寸SVG）を作る API。

仕様は docs/senrolab/openapi.yaml。
- POST /v1/nets: 種類と寸法（1/150 に縮めた後の mm）から、用紙ごとの SVG を返す
- GET  /health : 死活確認

駅舎・建物（station, building）は、この Web アプリの切妻屋根の建物の部品（generator.py）を、用紙に詰めて並べる。
用紙に収まらない大きさのときは、平らな屋根の箱形にする。
トンネル・鉄橋・高架橋・ホーム・名所・山・水面などは、この部品の作り方で作る。
"""
from __future__ import annotations

import hmac
import math
import os
from typing import Literal
from xml.sax.saxutils import escape

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import generator
from .generator import ModelSpec

router = APIRouter()

Kind = Literal["tunnel", "bridge", "viaduct", "station", "platform", "building", "landmark", "mountain", "water", "other"]
Paper = Literal["A4", "A3"]

KIND_LABELS = {
    "tunnel": "トンネル",
    "bridge": "鉄橋",
    "viaduct": "高架橋",
    "station": "駅舎",
    "platform": "ホーム",
    "building": "建物",
    "landmark": "名所・ランドマーク",
    "mountain": "山・丘",
    "water": "川・海・湖",
    "other": "その他",
}

#: 用紙（縦置き、mm）
PAPERS = {"A4": (210.0, 297.0), "A3": (297.0, 420.0)}
MARGIN = 8.0
HEADER = 18.0
TAB = 6.0
GAP = 4.0
#: トンネルの内側に必要な高さ(mm)。Nゲージの車両（レール面から約25mm）が通る高さ
TUNNEL_MIN_HEIGHT = 30.0
TUNNEL_MIN_WIDTH = 40.0
MAX_PAGES = 20
SCALE = 150

COLORS = {
    "tunnel": "#d9cbb8",
    "bridge": "#c9d3de",
    "viaduct": "#d6d6d0",
    "station": "#efe4cf",
    "platform": "#dcd7cb",
    "building": "#e9e1d2",
    "landmark": "#e6dcef",
    "mountain": "#cfe0c2",
    "water": "#bfdcf2",
    "other": "#e8e8e8",
}


class SimObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    kind: Kind
    length: float = Field(ge=1, le=2000, description="線路に沿った方向の長さ(mm)")
    width: float = Field(ge=1, le=800, description="線路と直角の方向の幅(mm)")
    height: float = Field(ge=0, le=400, description="高さ(mm)")
    note: str = Field(default="", max_length=200)


class NetsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["senrolab"]
    scale: Literal["1/150"] = "1/150"
    paper: Paper = "A4"
    object: SimObject
    notice: str = Field(default="", max_length=300)


def f(n: float) -> str:
    return f"{round(n, 2):g}"


def pts(points) -> str:
    return " ".join(f"{f(a)},{f(b)}" for a, b in points)


def usable(paper: str) -> tuple[float, float]:
    w, h = PAPERS[paper]
    return w - MARGIN * 2, h - MARGIN * 2 - HEADER


class Part:
    """用紙に並べる部品。draw(x, y) が SVG の断片を返す"""

    def __init__(self, label: str, w: float, h: float, draw):
        self.label, self.w, self.h, self._draw = label, w, h, draw

    def draw(self, x: float, y: float) -> str:
        return self._draw(x, y)


def grid_part(label, cols, rows, fill, tabs=None, decorate=None) -> Part:
    """長方形を格子に区切った部品（壁の帯・屋根・床など）。tabs は上下左右ののりしろ"""
    tabs = tabs or {}
    W, H = sum(cols), sum(rows)
    tl = TAB if tabs.get("left") else 0
    tt = TAB if tabs.get("top") else 0
    tr = TAB if tabs.get("right") else 0
    tb = TAB if tabs.get("bottom") else 0

    def draw(x, y):
        ox, oy = x + tl, y + tt
        out = []

        def tab(p):
            out.append(f'<polygon points="{pts(p)}" class="tab"/>')

        for on, y0, d in ((tabs.get("top"), oy, -1), (tabs.get("bottom"), oy + H, 1)):
            if not on:
                continue
            cx = ox
            for c in cols:
                s = min(2, c / 4)
                tab([(cx, y0), (cx + s, y0 + d * TAB), (cx + c - s, y0 + d * TAB), (cx + c, y0)])
                cx += c
        s = min(2, H / 4)
        if tabs.get("left"):
            tab([(ox, oy), (ox - TAB, oy + s), (ox - TAB, oy + H - s), (ox, oy + H)])
        if tabs.get("right"):
            tab([(ox + W, oy), (ox + W + TAB, oy + s), (ox + W + TAB, oy + H - s), (ox + W, oy + H)])
        out.append(f'<rect x="{f(ox)}" y="{f(oy)}" width="{f(W)}" height="{f(H)}" fill="{fill}" class="cut"/>')
        if decorate:
            out.append(decorate(ox, oy, W, H))

        def fold(x1, y1, x2, y2):
            out.append(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" class="fold"/>')

        cx = ox
        for c in cols[:-1]:
            cx += c
            fold(cx, oy, cx, oy + H)
        cy = oy
        for r in rows[:-1]:
            cy += r
            fold(ox, cy, ox + W, cy)
        if tabs.get("top"):
            fold(ox, oy, ox + W, oy)
        if tabs.get("bottom"):
            fold(ox, oy + H, ox + W, oy + H)
        if tabs.get("left"):
            fold(ox, oy, ox, oy + H)
        if tabs.get("right"):
            fold(ox + W, oy, ox + W, oy + H)
        out.append(f'<text x="{f(ox + 2)}" y="{f(oy + 4)}" class="label">{escape(label)}</text>')
        return "".join(out)

    return Part(label, tl + W + tr, tt + H + tb, draw)


def split_grid(label, cols, rows, fill, max_w, tabs=None, decorate=None) -> list[Part]:
    """横に長すぎる格子の部品を、用紙に収まる幅に分ける。分けた右端には貼り合わせ用ののりしろを付ける"""
    tabs = tabs or {}
    limit = max_w - (TAB if tabs.get("left") else 0) - TAB
    pieces: list[float] = []
    for c in cols:
        if c <= limit:
            pieces.append(c)
        else:
            n = math.ceil(c / limit)
            pieces += [c / n] * n
    total = (TAB if tabs.get("left") else 0) + sum(pieces) + (TAB if tabs.get("right") else 0)
    if total <= max_w:
        return [grid_part(label, pieces, rows, fill, tabs, decorate)]
    groups: list[list[float]] = []
    cur: list[float] = []
    w = 0.0
    for c in pieces:
        if cur and w + c > limit + 1e-9:
            groups.append(cur)
            cur, w = [], 0.0
        cur.append(c)
        w += c
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        t = dict(tabs)
        t["left"] = tabs.get("left") if i == 0 else False
        t["right"] = True if i < len(groups) - 1 else tabs.get("right")
        out.append(grid_part(f"{label}（{i + 1}/{len(groups)}）", g, rows, fill, t, decorate))
    return out


def portal_part(label: str, W: float, H: float, fill: str) -> Part:
    """トンネルの坑口。アーチ形の穴を描く"""
    ow = min(W - 8, 34)
    oh = min(H - 4, 42)

    def draw(x, y):
        r = ow / 2
        cx = x + W / 2
        by = y + H
        top = max(by - oh + r, y + r + 2)
        hole = f"M{f(cx - r)},{f(by)} L{f(cx - r)},{f(top)} A{f(r)},{f(r)} 0 0 1 {f(cx + r)},{f(top)} L{f(cx + r)},{f(by)} Z"
        stones = "".join(
            f'<line x1="{f(x)}" y1="{f(y + (i + 1) * 6)}" x2="{f(x + W)}" y2="{f(y + (i + 1) * 6)}" class="print"/>'
            for i in range(int(H // 6))
        )
        return (
            f'<polygon points="{pts([(x, by), (x + 2, by + TAB), (x + W - 2, by + TAB), (x + W, by)])}" class="tab"/>'
            f'<rect x="{f(x)}" y="{f(y)}" width="{f(W)}" height="{f(H)}" fill="{fill}" class="cut"/>'
            f"{stones}"
            f'<path d="{hole}" fill="#ffffff" class="cut"/>'
            f'<line x1="{f(x)}" y1="{f(by)}" x2="{f(x + W)}" y2="{f(by)}" class="fold"/>'
            f'<text x="{f(x + 2)}" y="{f(y + 4)}" class="label">{escape(label)}</text>'
        )

    return Part(label, W, H + TAB, draw)


def hill_part(label: str, L: float, W: float, H: float, fill: str) -> Part:
    """山（四角錐台）: 上面のまわりに4枚の斜面がつく"""
    a, b = L * 0.45, W * 0.45
    sL = math.hypot(H, (W - b) / 2)
    sW = math.hypot(H, (L - a) / 2)
    w = max(a + 2 * sW, L)
    h = max(b + 2 * sL, W)

    def draw(x, y):
        cx, cy = x + w / 2, y + h / 2
        x0, x1, y0, y1 = cx - a / 2, cx + a / 2, cy - b / 2, cy + b / 2

        def poly(p):
            return f'<polygon points="{pts(p)}" fill="{fill}" class="cut"/>'

        return (
            poly([(x0, y0), (x1, y0), (cx + L / 2, y0 - sL), (cx - L / 2, y0 - sL)])
            + poly([(x0, y1), (x1, y1), (cx + L / 2, y1 + sL), (cx - L / 2, y1 + sL)])
            + poly([(x0, y0), (x0, y1), (x0 - sW, cy + W / 2), (x0 - sW, cy - W / 2)])
            + poly([(x1, y0), (x1, y1), (x1 + sW, cy + W / 2), (x1 + sW, cy - W / 2)])
            + f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(a)}" height="{f(b)}" fill="{fill}" class="fold"/>'
            + f'<text x="{f(x0 + 2)}" y="{f(y0 + 4)}" class="label">{escape(label)}</text>'
        )

    return Part(label, w, h, draw)


def truss(ox, oy, W, H):
    n = max(1, round(W / max(H, 8)))
    step = W / n
    return "".join(
        f'<polyline points="{pts([(ox + i * step, oy + H), (ox + i * step + step / 2, oy), (ox + (i + 1) * step, oy + H)])}" class="print" fill="none"/>'
        for i in range(n)
    )


def windows(ox, oy, W, H):
    if H < 14:
        return ""
    out = []
    for r in range(int((H - 6) // 12)):
        x = ox + 4
        while x + 5 <= ox + W - 3:
            out.append(f'<rect x="{f(x)}" y="{f(oy + 6 + r * 12)}" width="5" height="6" class="window"/>')
            x += 9
    return "".join(out)


def arches(ox, oy, W, H):
    n = max(1, int(W // 40))
    s = W / n
    out = []
    for i in range(n):
        r = min(s * 0.35, H * 0.4)
        cx = ox + i * s + s / 2
        out.append(
            f'<path d="M{f(cx - r)},{f(oy + H)} L{f(cx - r)},{f(oy + H - r)} A{f(r)},{f(r)} 0 0 1 {f(cx + r)},{f(oy + H - r)} L{f(cx + r)},{f(oy + H)}" class="print" fill="none"/>'
        )
    return "".join(out)


def waves(ox, oy, W, H):
    return "".join(
        f'<path d="M{f(ox + 3 + j * 16)},{f(oy + 6 + i * 8)} q4,-2 8,0 t8,0" class="print" fill="none"/>'
        for i in range(int(H // 8))
        for j in range(int((W - 6) // 16))
    )


def build_parts(o: SimObject, paper: str) -> tuple[list[Part], list[str]]:
    L, W, H, kind = o.length, o.width, o.height, o.kind
    fill = COLORS[kind]
    max_w, max_h = usable(paper)
    parts: list[Part] = []
    warnings: list[str] = []

    def add(label, cols, rows, tabs=None, decorate=None):
        parts.extend(split_grid(label, cols, rows, fill, max_w, tabs, decorate))

    if kind == "tunnel":
        h = max(H, TUNNEL_MIN_HEIGHT)
        if h != H:
            warnings.append(f"トンネルの高さを{f(H)}mmから{f(h)}mmにしました（列車が通る高さ）")
        w = max(W, TUNNEL_MIN_WIDTH)
        if w != W:
            warnings.append(f"トンネルの幅を{f(W)}mmから{f(w)}mmにしました（線路1本が通る幅）")
        add("トンネルの覆い（側壁・天井・側壁）", [L], [h, w, h], {"top": True, "bottom": True})
        parts += [portal_part("坑口（手前）", w, h, fill), portal_part("坑口（奥）", w, h, fill)]
    elif kind == "bridge":
        d = min(max(H, 8), 30)
        add("橋げた（側面）", [L], [d], {"top": True}, truss)
        add("橋げた（側面）", [L], [d], {"top": True}, truss)
        add("床（線路を載せる）", [L], [W])
    elif kind == "viaduct":
        h = max(H, 10)
        add("高架橋（側面）", [L], [h], {"top": True, "bottom": True}, arches)
        add("高架橋（側面）", [L], [h], {"top": True, "bottom": True}, arches)
        add("床（線路を載せる）", [L], [W])
    elif kind == "water":
        add("水面", [L], [W], None, waves)
    elif kind == "mountain":
        hill = hill_part("山", L, W, max(H, 10), fill)
        if hill.w > max_w:
            warnings.append(f"山の展開図（幅{f(hill.w)}mm）が用紙（{paper}）に収まりません。大きい用紙で印刷してください")
        parts.append(hill)
    else:
        # 箱形（ホーム・名所など）: 四方の壁を1本の帯にし、上面を別にする
        h = max(H, 3)
        add("壁（4面）", [L, W, L, W], [h], {"top": True, "bottom": True, "right": True}, None if kind == "platform" else windows)
        add("上面" if kind == "platform" else "屋根", [L], [W])
    for p in parts:
        if p.h > max_h:
            warnings.append(f"「{p.label}」（高さ{f(p.h)}mm）が用紙（{paper}）に収まりません。大きい用紙で印刷してください")
    return parts, warnings


def layout(parts: list[Part], paper: str) -> list[list[tuple[Part, float, float]]]:
    """高い順に、左から右・上から下へ並べる。あふれたら次の用紙"""
    max_w, max_h = usable(paper)
    pages: list[list[tuple[Part, float, float]]] = [[]]
    x = y = row_h = 0.0
    for p in sorted(parts, key=lambda p: -p.h):
        if x > 0 and x + p.w > max_w:
            x, y, row_h = 0.0, y + row_h + GAP, 0.0
        if y > 0 and y + p.h > max_h:
            pages.append([])
            x = y = row_h = 0.0
        pages[-1].append((p, x, y))
        x += p.w + GAP
        row_h = max(row_h, p.h)
    return pages


STYLE = (
    ".cut{stroke:#222;stroke-width:0.3}"
    ".fold{stroke:#555;stroke-width:0.25;stroke-dasharray:2 1.2;fill:none}"
    ".tab{fill:#eeeeee;stroke:#222;stroke-width:0.3}"
    ".print{stroke:#7a6f60;stroke-width:0.2}"
    ".window{fill:#9fb3c8}"
    ".label{font-size:3px;fill:#555;font-family:sans-serif}"
    ".head{font-size:4.2px;fill:#222;font-family:sans-serif;font-weight:bold}"
    ".note{font-size:2.8px;fill:#555;font-family:sans-serif}"
    ".scale{stroke:#222;stroke-width:0.3}"
)


def page_svg(placed, title: str, paper: str, page_no: int, page_count: int, notice: str) -> str:
    pw, ph = PAPERS[paper]
    ox, oy = MARGIN, MARGIN + HEADER
    sx = pw - MARGIN - 50
    body = "".join(part.draw(ox + x, oy + y) for part, x, y in placed)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{f(pw)}mm" height="{f(ph)}mm" viewBox="0 0 {f(pw)} {f(ph)}">'
        f"<style>{STYLE}</style>"
        f'<rect width="{f(pw)}" height="{f(ph)}" fill="#ffffff"/>'
        f'<text x="{MARGIN}" y="{MARGIN + 4}" class="head">{escape(title)}（{page_no}/{page_count}）</text>'
        f'<text x="{MARGIN}" y="{MARGIN + 9}" class="note">{escape(notice)}</text>'
        f'<text x="{MARGIN}" y="{MARGIN + 13}" class="note">実線=切る・点線=折る・灰色=のりしろ。拡大・縮小せず実寸（100%）で印刷し、右の目盛りが50mmか確かめてください。</text>'
        f'<line x1="{f(sx)}" y1="{MARGIN + 16}" x2="{f(sx + 50)}" y2="{MARGIN + 16}" class="scale"/>'
        f'<line x1="{f(sx)}" y1="{MARGIN + 14}" x2="{f(sx)}" y2="{MARGIN + 18}" class="scale"/>'
        f'<line x1="{f(sx + 50)}" y1="{MARGIN + 14}" x2="{f(sx + 50)}" y2="{MARGIN + 18}" class="scale"/>'
        f'<text x="{f(sx + 20)}" y="{MARGIN + 4}" class="note">50mm</text>'
        f"{body}</svg>"
    )


def building_spec(o: SimObject) -> ModelSpec:
    """駅舎・建物を、この Web アプリの切妻屋根の建物（実物の m 単位）に換算する。高さの約3割を屋根にする"""
    to_m = SCALE / 1000.0
    total = max(o.height, 6.0)
    wall = total * 0.7
    rise = total - wall
    half_depth = o.width / 2
    pitch = math.degrees(math.atan2(rise, half_depth))
    return ModelSpec(
        name=o.name,
        scale=SCALE,
        width_m=min(o.length * to_m, 100),
        depth_m=min(o.width * to_m, 100),
        height_m=min(wall * to_m, 50),
        overhang_m=0.3,
        pitch_deg=min(max(pitch, 10), 60),
        style="standard",
        roof="gable",
    )


GABLE_LABELS = {
    "Front wall": "正面の壁",
    "Back wall": "裏の壁",
    "Left wall": "左の壁（妻）",
    "Right wall": "右の壁（妻）",
    "Roof A": "屋根A",
    "Roof B": "屋根B",
}


def gable_parts(o: SimObject, paper: str) -> list[Part] | None:
    """切妻屋根の建物の部品（generator.py）。どれか1つでも用紙に収まらなければ None"""
    max_w, max_h = usable(paper)
    parts = []
    for gp in generator.build_parts(building_spec(o)):
        if gp["w"] > max_w or gp["h"] > max_h:
            return None
        label = GABLE_LABELS.get(gp["name"], gp["name"])
        body = "".join(generator._svg_graphic(g) for g in gp["graphics"])

        def draw(x, y, body=body, label=label):
            return (f'<g transform="translate({f(x)},{f(y)})">{body}</g>'
                    f'<text x="{f(x + 6)}" y="{f(y + 3.5)}" class="label">{escape(label)}</text>')

        parts.append(Part(label, gp["w"], gp["h"], draw))
    return parts


def generate(req: NetsRequest) -> dict:
    o = req.object
    title = f"{o.name}（{KIND_LABELS[o.kind]}・1/150・{f(o.length)}×{f(o.width)}×{f(o.height)}mm）"
    parts, warnings = build_parts(o, req.paper)
    if o.kind in ("station", "building"):
        gable = gable_parts(o, req.paper)
        if gable:
            parts = gable
            warnings = ["切妻屋根の建物として、高さの約3割を屋根にしました。窓と扉は印刷の模様です"]
        else:
            warnings.insert(0, "大きいので、屋根を平らにした箱形にしました")
    pages = layout(parts, req.paper)
    if len(pages) > MAX_PAGES:
        raise HTTPException(422, "展開図が20枚を超えます。大きさを小さくするか、大きい用紙を選んでください")
    return {
        "pages": [page_svg(placed, title, req.paper, i + 1, len(pages), req.notice) for i, placed in enumerate(pages)],
        "warnings": warnings,
    }


def check_token(authorization: str | None) -> None:
    token = os.environ.get("PAPERCRAFT_API_TOKEN", "").strip()
    if not token:
        return
    given = (authorization or "").removeprefix("Bearer ").strip() if (authorization or "").startswith("Bearer ") else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "トークンが正しくありません")


@router.post("/v1/nets")
def nets(req: NetsRequest, authorization: str | None = Header(default=None)):
    check_token(authorization)
    return generate(req)


@router.get("/health")
def health():
    return {"ok": True}
