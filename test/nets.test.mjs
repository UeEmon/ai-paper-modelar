import { test } from "node:test";
import assert from "node:assert/strict";
import { buildParts, generate, KINDS, layout, splitGrid, usableArea, TUNNEL_MIN_HEIGHT } from "../src/nets.mjs";
import { validateNetsRequest } from "../src/validate.mjs";

const notice = "SenroLab のシミュレーション上の仮オブジェクトです。";
const obj = (o) => ({ name: "テスト", kind: "building", length: 60, width: 40, height: 30, note: "", ...o });

test("どの種類でも、部品が用紙の幅に収まる", () => {
  for (const kind of KINDS) {
    for (const paper of ["A4", "A3"]) {
      const { parts } = buildParts(obj({ kind, length: 600, width: 60, height: 40 }), paper);
      const max = usableArea(paper);
      for (const p of parts) {
        if (kind === "mountain") continue; // 山は分けずに警告を出す
        assert.ok(p.w <= max.w + 1e-6, `${kind} ${paper} ${p.label} w=${p.w}`);
      }
    }
  }
});

test("長い帯は分けて、つなぎ目にのりしろを付ける", () => {
  const parts = splitGrid({ label: "覆い", cols: [500], rows: [30], tabs: { top: true }, fill: "#fff" }, 194);
  assert.ok(parts.length >= 3);
  assert.match(parts[0].label, /（1\/\d）/);
  const total = parts.reduce((s, p) => s + p.w, 0);
  assert.ok(total > 500, "のりしろの分だけ長い");
});

test("トンネルは列車が通る高さを確保し、坑口2枚を付ける", () => {
  const { parts, warnings } = buildParts(obj({ kind: "tunnel", length: 248, width: 60, height: 20 }));
  assert.ok(warnings.some((w) => w.includes(`${TUNNEL_MIN_HEIGHT}mm`)));
  assert.equal(parts.filter((p) => p.label.startsWith("坑口")).length, 2);
});

test("箱形は4面の壁の帯と屋根", () => {
  const { parts } = buildParts(obj({ kind: "station", length: 80, width: 30, height: 25 }));
  // 4面の帯（2×(80+30)mm）は A4 の幅に収まらないので2つに分ける
  assert.deepEqual(parts.map((p) => p.label), ["壁（4面）（1/2）", "壁（4面）（2/2）", "屋根"]);
  const small = buildParts(obj({ kind: "station", length: 40, width: 20, height: 25 })).parts;
  assert.deepEqual(small.map((p) => p.label), ["壁（4面）", "屋根"]);
});

test("用紙からあふれる分は次のページに送る", () => {
  const { parts } = buildParts(obj({ kind: "viaduct", length: 1500, width: 50, height: 60 }));
  const pages = layout(parts);
  const max = usableArea("A4");
  assert.ok(pages.length > 1);
  for (const page of pages) for (const { part, x, y } of page) {
    assert.ok(x + part.w <= max.w + 1e-6);
    assert.ok(y + part.h <= max.h + 1e-6 || y === 0);
  }
});

test("SVG は実寸（mm）で、名前と注意書きが入り、文字はエスケープする", () => {
  const { pages } = generate({ object: obj({ name: "<駅>&舎" }), paper: "A4", notice });
  assert.equal(pages.length, 1);
  assert.match(pages[0], /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg" width="210mm" height="297mm" viewBox="0 0 210 297">/);
  assert.ok(pages[0].includes("&lt;駅&gt;&amp;舎"));
  assert.ok(pages[0].includes(notice));
  assert.ok(!pages[0].includes("<script"));
});

test("要求の検査", () => {
  const good = { source: "senrolab", scale: "1/150", paper: "A4", object: obj(), notice };
  assert.equal(validateNetsRequest(good).ok, true);
  assert.equal(validateNetsRequest({ ...good, paper: "B5" }).ok, false);
  assert.equal(validateNetsRequest({ ...good, scale: "1/80" }).ok, false);
  assert.equal(validateNetsRequest({ ...good, object: obj({ kind: "ufo" }) }).ok, false);
  assert.equal(validateNetsRequest({ ...good, object: obj({ length: 0 }) }).ok, false);
  assert.equal(validateNetsRequest({ ...good, object: obj({ name: "" }) }).ok, false);
  assert.equal(validateNetsRequest(null).ok, false);
});
