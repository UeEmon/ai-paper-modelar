// 要求の検査（docs/senrolab/openapi.yaml の NetsRequest）

import { KINDS, PAPERS } from "./nets.mjs";

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const isStr = (v) => typeof v === "string";

/** 正しければ { ok: true, value }、違えば { ok: false, error } */
export function validateNetsRequest(body) {
  const bad = (error) => ({ ok: false, error });
  if (!body || typeof body !== "object" || Array.isArray(body)) return bad("要求の形が正しくありません（JSONのオブジェクト）");
  const { paper = "A4", object, notice = "" } = body;
  if (body.scale !== undefined && body.scale !== "1/150") return bad("縮尺は 1/150 だけに対応しています");
  if (!Object.hasOwn(PAPERS, paper)) return bad("用紙は A4 か A3 を指定してください");
  if (!isStr(notice) || notice.length > 300) return bad("notice は300文字までの文字列です");
  if (!object || typeof object !== "object") return bad("object がありません");
  const { name, kind, length, width, height, note = "" } = object;
  if (!isStr(name) || !name.trim() || name.length > 60) return bad("名前（object.name）は1〜60文字です");
  if (!KINDS.includes(kind)) return bad(`種類（object.kind）は ${KINDS.join(", ")} のどれかです`);
  if (!isNum(length) || length < 1 || length > 2000) return bad("長さ（object.length）は1〜2000mmです");
  if (!isNum(width) || width < 1 || width > 800) return bad("幅（object.width）は1〜800mmです");
  if (!isNum(height) || height < 0 || height > 400) return bad("高さ（object.height）は0〜400mmです");
  if (!isStr(note) || note.length > 200) return bad("note は200文字までの文字列です");
  return { ok: true, value: { paper, notice, object: { name: name.trim(), kind, length, width, height, note } } };
}
