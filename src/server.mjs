// 展開図API のサーバー（依存なし、Node 22 の標準機能だけ）
//   POST /v1/nets  仮オブジェクト1個 → 用紙ごとの実寸SVG
//   GET  /health   死活確認
// 仕様: docs/senrolab/openapi.yaml

import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import { generate } from "./nets.mjs";
import { validateNetsRequest } from "./validate.mjs";

/** 受け付ける本文の上限（バイト） */
const MAX_BODY = 16 * 1024;

function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(data),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  res.end(data);
}

function tokenOk(req, token) {
  if (!token) return true;
  const m = /^Bearer (.+)$/.exec(req.headers.authorization ?? "");
  if (!m) return false;
  const a = Buffer.from(m[1]);
  const b = Buffer.from(token);
  return a.length === b.length && timingSafeEqual(a, b);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      // 上限を超えたら捨てて読み切り、413 を返す（途中で切ると相手に応答が届かない）
      if (size <= MAX_BODY) chunks.push(c);
    });
    req.on("end", () =>
      size > MAX_BODY ? reject(Object.assign(new Error("too large"), { status: 413 })) : resolve(Buffer.concat(chunks).toString("utf8")),
    );
    req.on("error", reject);
  });
}

/** テストからも使えるよう、サーバーを作る関数にする */
export function createServer({ token = process.env.PAPERCRAFT_API_TOKEN?.trim() || "" } = {}) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    try {
      if (url.pathname === "/health") {
        if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, { error: "GET で呼んでください" });
        return send(res, 200, { ok: true });
      }
      if (url.pathname === "/v1/nets") {
        if (req.method !== "POST") return send(res, 405, { error: "POST で呼んでください" });
        if (!tokenOk(req, token)) return send(res, 401, { error: "トークンが正しくありません" });
        if (!/^application\/json\b/i.test(req.headers["content-type"] ?? "")) return send(res, 415, { error: "Content-Type は application/json です" });
        let body;
        try {
          body = JSON.parse(await readBody(req));
        } catch (err) {
          if (err?.status === 413) return send(res, 413, { error: "要求が大きすぎます" });
          return send(res, 400, { error: "JSON として読めません" });
        }
        const v = validateNetsRequest(body);
        if (!v.ok) return send(res, 400, { error: v.error });
        const result = generate(v.value);
        if (result.pages.length > 20) return send(res, 422, { error: "展開図が20枚を超えます。大きさを小さくするか、大きい用紙を選んでください" });
        return send(res, 200, result);
      }
      return send(res, 404, { error: "見つかりません" });
    } catch (err) {
      console.error("nets failed", err);
      if (!res.headersSent) send(res, 500, { error: "展開図を作れませんでした" });
    }
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.PORT ?? 8080);
  const server = createServer();
  server.listen(port, "0.0.0.0", () => console.log(`ai-paper-modelar: listening on ${port}`));
  const stop = () => server.close(() => process.exit(0));
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
}
