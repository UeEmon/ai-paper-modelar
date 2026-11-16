// 立体の種類と寸法（mm）から、ペーパークラフトの展開図を作る。
// 部品（part）は「切り取り線・折り線・のりしろ」を持つ図形で、あとで用紙に並べる。
// 座標の単位はすべて mm（SVG の 1 = 1mm）。

export const KINDS = ["tunnel", "bridge", "viaduct", "station", "platform", "building", "landmark", "mountain", "water", "other"];

export const KIND_LABELS = {
  tunnel: "トンネル",
  bridge: "鉄橋",
  viaduct: "高架橋",
  station: "駅舎",
  platform: "ホーム",
  building: "建物",
  landmark: "名所・ランドマーク",
  mountain: "山・丘",
  water: "川・海・湖",
  other: "その他",
};

/** 用紙（縦置き、mm） */
export const PAPERS = {
  A4: { w: 210, h: 297 },
  A3: { w: 297, h: 420 },
};
/** 用紙の余白と、上の見出しの高さ(mm) */
export const MARGIN = 8;
export const HEADER = 18;
/** のりしろの幅(mm) */
export const TAB = 6;
/** 部品と部品のすき間(mm) */
export const GAP = 4;
/** トンネルの内側に必要な高さ(mm)。Nゲージの車両（レール面から約25mm）が通る高さ */
export const TUNNEL_MIN_HEIGHT = 30;

const COLORS = {
  tunnel: "#d9cbb8",
  bridge: "#c9d3de",
  viaduct: "#d6d6d0",
  station: "#efe4cf",
  platform: "#dcd7cb",
  building: "#e9e1d2",
  landmark: "#e6dcef",
  mountain: "#cfe0c2",
  water: "#bfdcf2",
  other: "#e8e8e8",
};

const f = (n) => Number(n.toFixed(2));

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** 用紙の中で部品を置ける範囲 */
export function usableArea(paper) {
  const p = PAPERS[paper];
  return { w: p.w - MARGIN * 2, h: p.h - MARGIN * 2 - HEADER };
}

const pts = (list) => list.map(([a, b]) => `${f(a)},${f(b)}`).join(" ");

/**
 * 長方形を格子に区切った部品（壁を並べた帯、屋根、床など）。
 * cols は横方向の区切り（折り線）、rows は縦方向の区切り。tabs は上下左右の辺に付けるのりしろ。
 */
function gridPart({ label, cols, rows, tabs = {}, fill, decorate }) {
  const W = cols.reduce((a, b) => a + b, 0);
  const H = rows.reduce((a, b) => a + b, 0);
  const tl = tabs.left ? TAB : 0;
  const tt = tabs.top ? TAB : 0;
  const tr = tabs.right ? TAB : 0;
  const tb = tabs.bottom ? TAB : 0;
  return {
    label,
    w: tl + W + tr,
    h: tt + H + tb,
    draw(x, y) {
      const ox = x + tl;
      const oy = y + tt;
      const out = [];
      const tab = (p) => out.push(`<polygon points="${pts(p)}" class="tab"/>`);
      for (const [on, y0, dir] of [
        [tabs.top, oy, -1],
        [tabs.bottom, oy + H, 1],
      ]) {
        if (!on) continue;
        let cx = ox;
        for (const c of cols) {
          const s = Math.min(2, c / 4);
          tab([[cx, y0], [cx + s, y0 + dir * TAB], [cx + c - s, y0 + dir * TAB], [cx + c, y0]]);
          cx += c;
        }
      }
      const s = Math.min(2, H / 4);
      if (tabs.left) tab([[ox, oy], [ox - TAB, oy + s], [ox - TAB, oy + H - s], [ox, oy + H]]);
      if (tabs.right) tab([[ox + W, oy], [ox + W + TAB, oy + s], [ox + W + TAB, oy + H - s], [ox + W, oy + H]]);
      out.push(`<rect x="${f(ox)}" y="${f(oy)}" width="${f(W)}" height="${f(H)}" fill="${fill}" class="cut"/>`);
      if (decorate) out.push(decorate(ox, oy, W, H));
      const line = (x1, y1, x2, y2) => out.push(`<line x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}" class="fold"/>`);
      let cx = ox;
      for (const c of cols.slice(0, -1)) line((cx += c), oy, cx, oy + H);
      let cy = oy;
      for (const r of rows.slice(0, -1)) line(ox, (cy += r), ox + W, cy);
      // のりしろの付け根も折り線
      if (tabs.top) line(ox, oy, ox + W, oy);
      if (tabs.bottom) line(ox, oy + H, ox + W, oy + H);
      if (tabs.left) line(ox, oy, ox, oy + H);
      if (tabs.right) line(ox + W, oy, ox + W, oy + H);
      out.push(`<text x="${f(ox + 2)}" y="${f(oy + 4)}" class="label">${esc(label)}</text>`);
      return out.join("");
    },
  };
}

/**
 * 横に長すぎる格子の部品を、用紙に収まる幅に分ける。
 * 折り線の所で分け、1列でも長すぎるときはその列を等分する。分けた右端には、次の部品と貼り合わせるのりしろを付ける。
 */
export function splitGrid(spec, maxW) {
  const limit = maxW - (spec.tabs?.left ? TAB : 0) - TAB;
  const cols = [];
  for (const c of spec.cols) {
    if (c <= limit) cols.push(c);
    else {
      const n = Math.ceil(c / limit);
      for (let i = 0; i < n; i++) cols.push(c / n);
    }
  }
  const total = (spec.tabs?.left ? TAB : 0) + cols.reduce((a, b) => a + b, 0) + (spec.tabs?.right ? TAB : 0);
  if (total <= maxW) return [gridPart({ ...spec, cols })];
  const groups = [];
  let cur = [];
  let w = 0;
  for (const c of cols) {
    if (cur.length && w + c > limit + 1e-9) {
      groups.push(cur);
      cur = [];
      w = 0;
    }
    cur.push(c);
    w += c;
  }
  if (cur.length) groups.push(cur);
  return groups.map((g, i) =>
    gridPart({
      ...spec,
      label: `${spec.label}（${i + 1}/${groups.length}）`,
      cols: g,
      tabs: { ...spec.tabs, left: i === 0 ? spec.tabs?.left : false, right: i < groups.length - 1 ? true : spec.tabs?.right },
    }),
  );
}

/** トンネルの坑口（入口の壁）。アーチ形の穴を描く */
function portalPart(label, W, H, fill) {
  const ow = Math.min(W - 8, 34);
  const oh = Math.min(H - 4, 42);
  return {
    label,
    w: W,
    h: H + TAB,
    draw(x, y) {
      const r = ow / 2;
      const cx = x + W / 2;
      const by = y + H;
      const top = Math.max(by - oh + r, y + r + 2);
      const hole = `M${f(cx - r)},${f(by)} L${f(cx - r)},${f(top)} A${f(r)},${f(r)} 0 0 1 ${f(cx + r)},${f(top)} L${f(cx + r)},${f(by)} Z`;
      const stones = Array.from({ length: Math.floor(H / 6) }, (_, i) => `<line x1="${f(x)}" y1="${f(y + (i + 1) * 6)}" x2="${f(x + W)}" y2="${f(y + (i + 1) * 6)}" class="print"/>`);
      return [
        `<polygon points="${pts([[x, by], [x + 2, by + TAB], [x + W - 2, by + TAB], [x + W, by]])}" class="tab"/>`,
        `<rect x="${f(x)}" y="${f(y)}" width="${f(W)}" height="${f(H)}" fill="${fill}" class="cut"/>`,
        ...stones,
        `<path d="${hole}" fill="#ffffff" class="cut"/>`,
        `<line x1="${f(x)}" y1="${f(by)}" x2="${f(x + W)}" y2="${f(by)}" class="fold"/>`,
        `<text x="${f(x + 2)}" y="${f(y + 4)}" class="label">${esc(label)}</text>`,
      ].join("");
    },
  };
}

/** 山（四角錐台）。上面のまわりに4枚の斜面がつく展開図 */
function hillPart(label, L, W, H, fill) {
  const a = L * 0.45;
  const b = W * 0.45;
  const sL = Math.hypot(H, (W - b) / 2);
  const sW = Math.hypot(H, (L - a) / 2);
  const w = Math.max(a + 2 * sW, L);
  const h = Math.max(b + 2 * sL, W);
  return {
    label,
    w,
    h,
    draw(x, y) {
      const cx = x + w / 2;
      const cy = y + h / 2;
      const x0 = cx - a / 2;
      const x1 = cx + a / 2;
      const y0 = cy - b / 2;
      const y1 = cy + b / 2;
      const poly = (p) => `<polygon points="${pts(p)}" fill="${fill}" class="cut"/>`;
      return [
        poly([[x0, y0], [x1, y0], [cx + L / 2, y0 - sL], [cx - L / 2, y0 - sL]]),
        poly([[x0, y1], [x1, y1], [cx + L / 2, y1 + sL], [cx - L / 2, y1 + sL]]),
        poly([[x0, y0], [x0, y1], [x0 - sW, cy + W / 2], [x0 - sW, cy - W / 2]]),
        poly([[x1, y0], [x1, y1], [x1 + sW, cy + W / 2], [x1 + sW, cy - W / 2]]),
        `<rect x="${f(x0)}" y="${f(y0)}" width="${f(a)}" height="${f(b)}" fill="${fill}" class="fold"/>`,
        `<text x="${f(x0 + 2)}" y="${f(y0 + 4)}" class="label">${esc(label)}</text>`,
      ].join("");
    },
  };
}

const trussDeco = (ox, oy, W, H) => {
  const n = Math.max(1, Math.round(W / Math.max(H, 8)));
  const step = W / n;
  const out = [];
  for (let i = 0; i < n; i++) {
    const x0 = ox + i * step;
    out.push(`<polyline points="${pts([[x0, oy + H], [x0 + step / 2, oy], [x0 + step, oy + H]])}" class="print" fill="none"/>`);
  }
  return out.join("");
};

const windowDeco = (ox, oy, W, H) => {
  if (H < 14) return "";
  const out = [];
  const rows = Math.floor((H - 6) / 12);
  for (let r = 0; r < rows; r++) {
    for (let x = ox + 4; x + 5 <= ox + W - 3; x += 9) out.push(`<rect x="${f(x)}" y="${f(oy + 6 + r * 12)}" width="5" height="6" class="window"/>`);
  }
  return out.join("");
};

const archDeco = (ox, oy, W, H) => {
  const n = Math.max(1, Math.floor(W / 40));
  const s = W / n;
  const out = [];
  for (let i = 0; i < n; i++) {
    const r = Math.min(s * 0.35, H * 0.4);
    const cx = ox + i * s + s / 2;
    out.push(`<path d="M${f(cx - r)},${f(oy + H)} L${f(cx - r)},${f(oy + H - r)} A${f(r)},${f(r)} 0 0 1 ${f(cx + r)},${f(oy + H - r)} L${f(cx + r)},${f(oy + H)}" class="print" fill="none"/>`);
  }
  return out.join("");
};

const waveDeco = (ox, oy, W, H) =>
  Array.from({ length: Math.floor(H / 8) }, (_, i) =>
    Array.from({ length: Math.floor((W - 6) / 16) }, (_, j) => `<path d="M${f(ox + 3 + j * 16)},${f(oy + 6 + i * 8)} q4,-2 8,0 t8,0" class="print" fill="none"/>`).join(""),
  ).join("");

/**
 * 仮オブジェクト1個の部品を作る。
 * 部品はどれも用紙の幅に収まるよう分ける。高さが収まらないときは警告を返す。
 */
export function buildParts(obj, paper = "A4") {
  const { kind } = obj;
  const L = obj.length;
  const W = obj.width;
  const H = obj.height;
  const fill = COLORS[kind] ?? COLORS.other;
  const max = usableArea(paper);
  const warnings = [];
  const parts = [];
  const add = (spec) => parts.push(...splitGrid({ fill, ...spec }, max.w));

  switch (kind) {
    case "tunnel": {
      const h = Math.max(H, TUNNEL_MIN_HEIGHT);
      if (h !== H) warnings.push(`トンネルの高さを${f(H)}mmから${h}mmにしました（列車が通る高さ）`);
      const w = Math.max(W, 40);
      if (w !== W) warnings.push(`トンネルの幅を${f(W)}mmから${w}mmにしました（線路1本が通る幅）`);
      add({ label: "トンネルの覆い（側壁・天井・側壁）", cols: [L], rows: [h, w, h], tabs: { top: true, bottom: true } });
      parts.push(portalPart("坑口（手前）", w, h, fill), portalPart("坑口（奥）", w, h, fill));
      break;
    }
    case "bridge": {
      const d = Math.min(Math.max(H, 8), 30);
      add({ label: "橋げた（側面）", cols: [L], rows: [d], tabs: { top: true }, decorate: trussDeco });
      add({ label: "橋げた（側面）", cols: [L], rows: [d], tabs: { top: true }, decorate: trussDeco });
      add({ label: "床（線路を載せる）", cols: [L], rows: [W] });
      break;
    }
    case "viaduct": {
      const h = Math.max(H, 10);
      add({ label: "高架橋（側面）", cols: [L], rows: [h], tabs: { top: true, bottom: true }, decorate: archDeco });
      add({ label: "高架橋（側面）", cols: [L], rows: [h], tabs: { top: true, bottom: true }, decorate: archDeco });
      add({ label: "床（線路を載せる）", cols: [L], rows: [W] });
      break;
    }
    case "water":
      add({ label: "水面", cols: [L], rows: [W], decorate: waveDeco });
      break;
    case "mountain": {
      const hill = hillPart("山", L, W, Math.max(H, 10), fill);
      if (hill.w > max.w) warnings.push(`山の展開図（幅${f(hill.w)}mm）が用紙（${paper}）に収まりません。大きい用紙で印刷してください`);
      parts.push(hill);
      break;
    }
    default: {
      // 箱形（駅舎・建物・ホーム・名所など）: 四方の壁を1本の帯にし、屋根（上面）を別にする
      const h = Math.max(H, 3);
      add({ label: "壁（4面）", cols: [L, W, L, W], rows: [h], tabs: { top: true, bottom: true, right: true }, decorate: kind === "platform" ? undefined : windowDeco });
      add({ label: kind === "platform" ? "上面" : "屋根", cols: [L], rows: [W] });
    }
  }
  for (const p of parts) {
    if (p.h > max.h) warnings.push(`「${p.label}」（高さ${f(p.h)}mm）が用紙（${paper}）に収まりません。大きい用紙で印刷してください`);
  }
  return { parts, warnings };
}

/** 部品を用紙に並べる（高い順に、左から右・上から下へ）。用紙ごとの [{part, x, y}] を返す */
export function layout(parts, paper = "A4") {
  const max = usableArea(paper);
  const sorted = [...parts].sort((a, b) => b.h - a.h);
  const pages = [[]];
  let x = 0;
  let y = 0;
  let rowH = 0;
  for (const p of sorted) {
    if (x > 0 && x + p.w > max.w) {
      x = 0;
      y += rowH + GAP;
      rowH = 0;
    }
    if (y > 0 && y + p.h > max.h) {
      pages.push([]);
      x = 0;
      y = 0;
      rowH = 0;
    }
    pages[pages.length - 1].push({ part: p, x, y });
    x += p.w + GAP;
    rowH = Math.max(rowH, p.h);
  }
  return pages;
}

const STYLE = [
  ".cut{stroke:#222;stroke-width:0.3}",
  ".fold{stroke:#555;stroke-width:0.25;stroke-dasharray:2 1.2;fill:none}",
  ".tab{fill:#eeeeee;stroke:#222;stroke-width:0.3}",
  ".print{stroke:#7a6f60;stroke-width:0.2}",
  ".window{fill:#9fb3c8}",
  ".label{font-size:3px;fill:#555;font-family:sans-serif}",
  ".head{font-size:4.2px;fill:#222;font-family:sans-serif;font-weight:bold}",
  ".note{font-size:2.8px;fill:#555;font-family:sans-serif}",
  ".scale{stroke:#222;stroke-width:0.3}",
].join("");

/** 1枚の用紙のSVG（実寸。width/height を mm で指定し、1 = 1mm） */
export function pageSvg(placed, { title, paper, pageNo, pageCount, notice }) {
  const p = PAPERS[paper];
  const ox = MARGIN;
  const oy = MARGIN + HEADER;
  const sx = p.w - MARGIN - 50;
  const body = placed.map(({ part, x, y }) => part.draw(ox + x, oy + y)).join("");
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${p.w}mm" height="${p.h}mm" viewBox="0 0 ${p.w} ${p.h}">`,
    `<style>${STYLE}</style>`,
    `<rect width="${p.w}" height="${p.h}" fill="#ffffff"/>`,
    `<text x="${MARGIN}" y="${MARGIN + 4}" class="head">${esc(title)}（${pageNo}/${pageCount}）</text>`,
    `<text x="${MARGIN}" y="${MARGIN + 9}" class="note">${esc(notice)}</text>`,
    `<text x="${MARGIN}" y="${MARGIN + 13}" class="note">実線=切る・点線=折る・灰色=のりしろ。拡大・縮小せず実寸（100%）で印刷し、右の目盛りが50mmか確かめてください。</text>`,
    `<line x1="${sx}" y1="${MARGIN + 16}" x2="${sx + 50}" y2="${MARGIN + 16}" class="scale"/>`,
    `<line x1="${sx}" y1="${MARGIN + 14}" x2="${sx}" y2="${MARGIN + 18}" class="scale"/>`,
    `<line x1="${sx + 50}" y1="${MARGIN + 14}" x2="${sx + 50}" y2="${MARGIN + 18}" class="scale"/>`,
    `<text x="${sx + 20}" y="${MARGIN + 4}" class="note">50mm</text>`,
    body,
    `</svg>`,
  ].join("");
}

/** 要求（検査済み）から、用紙ごとのSVGと警告を作る */
export function generate({ object, paper, notice }) {
  const { parts, warnings } = buildParts(object, paper);
  const pages = layout(parts, paper);
  const title = `${object.name}（${KIND_LABELS[object.kind]}・1/150・${f(object.length)}×${f(object.width)}×${f(object.height)}mm）`;
  return {
    pages: pages.map((placed, i) => pageSvg(placed, { title, paper, pageNo: i + 1, pageCount: pages.length, notice })),
    warnings,
  };
}
