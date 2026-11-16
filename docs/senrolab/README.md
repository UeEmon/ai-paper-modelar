# SenroLab 連携: 展開図API の仕様

SenroLab（Nゲージのレイアウト設計アプリ、リポジトリ UeEmon/Nine-Gage-Systems）は、
「再現してみた」で作った**仮オブジェクト**（トンネル・鉄橋・駅舎・名所など、実在の製品にない物）を、
このジェネレーターに送って**ペーパークラフトの展開図**にしてもらう。
ai-paper-modelar は、この仕様のAPIを持つコンテナとして作れば SenroLab からそのまま使える。

機械が読める仕様は [openapi.yaml](openapi.yaml)。SenroLab 側の実装は
`src/lib/server/papercraft.ts`（UeEmon/Nine-Gage-Systems）。

## 全体の流れ

1. 利用者が SenroLab の画面で、仮オブジェクトの「展開図」を押す
2. SenroLab のサーバーが `POST {PAPERCRAFT_URL}/v1/nets` を呼ぶ（ブラウザからは呼ばない）
3. ジェネレーターが実寸の展開図を SVG（用紙1枚ずつ）で返す
4. SenroLab が SVG を `<img>` で並べた印刷用の画面を開き、利用者が 100%（実寸）で印刷する

## エンドポイント

### `POST /v1/nets`

要求:

| 項目 | 型 | 内容 |
| --- | --- | --- |
| `source` | `"senrolab"` | 呼び出し元 |
| `scale` | `"1/150"` | 縮尺。寸法はすでにこの縮尺の実寸 |
| `paper` | `"A4"` か `"A3"` | 用紙（縦置き）。いまの SenroLab は A4 だけ送る |
| `object.name` | 文字列（1〜60） | 名前。展開図の見出しに使う |
| `object.kind` | 下の表 | 種類 |
| `object.length` | 数（1〜2000） | 線路に沿った方向の長さ(mm) |
| `object.width` | 数（1〜800） | 線路と直角の方向の幅(mm) |
| `object.height` | 数（0〜400） | 高さ(mm) |
| `object.note` | 文字列（0〜200） | 実物のどんな特徴を表したか |
| `notice` | 文字列 | 展開図に印刷してほしい注意書き |

`kind` と、作ってほしい展開図の目安:

| kind | 物 | 展開図の目安 |
| --- | --- | --- |
| `tunnel` | トンネル | 線路をまたぐ覆い（側壁＋天井の帯）と、アーチ形の穴のある坑口2枚。列車が通る内側の高さ（約30mm以上）を確保 |
| `bridge` | 鉄橋 | 側面のけた2枚（トラス模様）と床 |
| `viaduct` | 高架橋 | 側面2枚（アーチ模様）と床。height は地面から線路面まで |
| `station` | 駅舎 | 箱形（4面の壁の帯＋屋根） |
| `platform` | ホーム | 低い箱形（4面＋上面） |
| `building` | 建物 | 箱形 |
| `landmark` | 名所（塔・寺社・城など） | 箱形を基本に。形を工夫してもよい |
| `mountain` | 山・丘 | 四角錐台など |
| `water` | 川・海・湖 | 平らな板 |
| `other` | その他 | 箱形 |

応答（200）:

```json
{ "pages": ["<svg …>…</svg>"], "warnings": ["…"] }
```

- `pages`: 用紙1枚ごとの SVG（1〜20枚）。`<svg` で始まる（`<?xml …?>` は前に付けてよい）。1枚 2,000,000 文字まで。
  - **実寸**: A4 なら `width="210mm" height="297mm" viewBox="0 0 210 297"` のように mm で指定し、1 = 1mm で描く。
  - SenroLab は `<img>` で表示するので、**SVG の中で完結**させる（スクリプト・外部の画像やフォントは読み込まれない）。日本語の文字は利用者の環境のフォントで表示される。
  - 用紙に収まらない長い部品は、のりしろを付けて分けるか、`warnings` で大きい用紙を勧める。
- `warnings`: 任意。利用者に見せる注意（日本語、20件・1件300文字まで）。

エラー: 4xx/5xx と `{ "error": "利用者に見せるメッセージ（日本語）" }`。
4xx は SenroLab の画面にそのまま出す。5xx・タイムアウト（既定30秒）・形の違う応答は「作れませんでした」になる。

### `GET /health`

動いていれば 200。中身は問わない。

## 展開図に入れてほしいもの

- 見出し: 名前・種類・ページ番号
- `notice` の注意書き（実在の製品・鉄道会社の公式なものではない旨）
- 「実線=切る・点線=折る・のりしろ」の凡例と、実寸の確認用の目盛り（例: 50mm）
- 鉄道会社のロゴ・商標・車両の塗装は入れない

## 認証と置き方

- 環境変数でトークンを設定した場合は、`Authorization: Bearer <トークン>` を確かめる（SenroLab の `PAPERCRAFT_API_TOKEN` と同じ値）。未設定なら認証なし。
- SenroLab と同じ内部ネットワークだけにつなぎ、ポートは公開しない。例:

```yaml
services:
  papercraft:
    image: ghcr.io/ueemon/ai-paper-modelar:stable
    expose: ["8080"]
    networks: [prod-edge]
  nine-gage:
    environment:
      PAPERCRAFT_URL: http://papercraft:8080
```

## 動作確認

```sh
curl -s http://localhost:8080/v1/nets -H 'Content-Type: application/json' -d '{
  "source":"senrolab","scale":"1/150","paper":"A4",
  "object":{"name":"テストトンネル","kind":"tunnel","length":248,"width":60,"height":40,"note":""},
  "notice":"SenroLab のシミュレーション上の仮オブジェクトです。"
}'
```
