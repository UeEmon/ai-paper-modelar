import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "../src/server.mjs";

let server;
let base;

before(async () => {
  server = createServer({ token: "secret" });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${server.address().port}`;
});
after(() => new Promise((r) => server.close(r)));

const body = {
  source: "senrolab",
  scale: "1/150",
  paper: "A4",
  object: { name: "テストトンネル", kind: "tunnel", length: 248, width: 60, height: 40, note: "" },
  notice: "SenroLab のシミュレーション上の仮オブジェクトです。",
};
const post = (b, headers = {}) =>
  fetch(`${base}/v1/nets`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer secret", ...headers },
    body: typeof b === "string" ? b : JSON.stringify(b),
  });

test("GET /health", async () => {
  const r = await fetch(`${base}/health`);
  assert.equal(r.status, 200);
});

test("POST /v1/nets は SVG のページを返す（SenroLab の検査と同じ条件）", async () => {
  const r = await post(body);
  assert.equal(r.status, 200);
  const d = await r.json();
  assert.ok(d.pages.length >= 1 && d.pages.length <= 20);
  for (const p of d.pages) {
    assert.match(p, /^\s*(<\?xml[^>]*>\s*)?<svg[\s>]/i);
    assert.ok(p.length <= 2_000_000);
  }
  assert.ok(Array.isArray(d.warnings));
});

test("トークンが違えば 401", async () => {
  const r = await post(body, { Authorization: "Bearer nope" });
  assert.equal(r.status, 401);
  assert.equal(typeof (await r.json()).error, "string");
});

test("入力が違えば 400 と日本語のメッセージ", async () => {
  const r = await post({ ...body, object: { ...body.object, kind: "ufo" } });
  assert.equal(r.status, 400);
  assert.match((await r.json()).error, /種類/);
  assert.equal((await post("{")).status, 400);
});

test("大きすぎる本文は 413", async () => {
  const r = await post({ ...body, notice: "x".repeat(20000) });
  assert.equal(r.status, 413);
});

test("知らない場所は 404", async () => {
  assert.equal((await fetch(`${base}/nope`)).status, 404);
});
