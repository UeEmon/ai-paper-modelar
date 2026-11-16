# AI Paper Modelar / 鉄道模型ジオラマ用ペーパークラフトジェネレーター

駅舎・橋梁・鉄道関連建物などの紙模型を設計するWebアプリの初期版です。

## 初期実装

- Wikipedia日本語版で駅舎・構造物を検索し、参考情報のURLを一覧表示。
- OpenAI・Gemini・AnthropicのAPIを切替可能。APIキーはサーバー側環境変数に保持。未設定ならオフライン案を表示。
- 忠実再現、標準デフォルメ、アニメ風、昭和レトロ、簡単組立を選択。
- 縮尺は1/150、1/160、1/80、1/87、1/220、任意1/20〜1/500。
- 幅、奥行、軒高、屋根、勾配を指定し、模型寸法とA4実寸PDF・SVGを生成。
- 50mm印刷チェック線、切断・折線・のりしろ表示、タイル分割。
- Docker Composeでローカル起動。
- 手持ち写真・設計図・PDF（JPEG/PNG/WebP/PDF）を最大8点アップロードし、サムネイルで確認・削除。資料ごとに方向とメモを付与。
- **利用者が明示的に許可した場合のみ**画像等のプレビューとPDF抽出テキストを選択中のAIプロバイダーに送信して文章案を作成。

## 起動方法

Docker Desktopを起動したら、リポジトリ直下で:

    cp .env.example .env
    docker compose up -d --build

ブラウザで http://localhost:8086 を開きます。API定義は http://localhost:8086/docs です。
停止コマンド:

    docker compose down

AI APIを使う場合は .env に AI_PROVIDER=openai と OPENAI_API_KEY=your-key などを設定してください。GeminiならAI_PROVIDER=gemini / GEMINI_API_KEY、AnthropicならAI_PROVIDER=anthropic / ANTHROPIC_API_KEYを使います。
モデル名は OPENAI_MODEL / GEMINI_MODEL / ANTHROPIC_MODEL で変更できます。APIキーをコミットしないでください。

## SenroLab 連携（展開図API）

SenroLab（Nゲージのレイアウト設計アプリ）の「再現してみた」で作った仮オブジェクトを、
`POST /v1/nets` で実寸の展開図（用紙ごとの SVG）にします。仕様は [docs/senrolab/](docs/senrolab/README.md)。

- 種類: トンネル・鉄橋・高架橋・駅舎・ホーム・建物・名所・山・水面・その他。駅舎・建物は切妻屋根の部品（app/generator.py）を用紙に詰めて並べ、用紙に収まらない大きさは箱形にします。
- 環境変数 `PAPERCRAFT_API_TOKEN` を設定すると `Authorization: Bearer <トークン>` を確かめます（SenroLab 側も同じ値）。
- `GET /health` で死活確認。
- イメージは CI が ghcr.io/ueemon/ai-paper-modelar に置きます（arm64）。main は `:main`、タグ `v*` は `:<版>` と `:stable`。

## テスト

    python -m pip install -r requirements-dev.txt
    pytest -q

## 自分で撮影した写真・設計図・PDFの追加

1. 「YOUR REFERENCES」でファイルを選択（1件15MB以内、画面上で最大8件）。対応拡張子は .jpg / .jpeg / .png / .webp / .pdf。
2. 正面、背面、左右側面、屋根、平面図、細部などを選び、任意のメモを入力して追加します。
3. 画像やPDF1ページ目のサムネイルを確認して、不要なら「削除」。
4. AI連携を使う場合は「資料をAI提案にも利用する」に明示的にチェックを入れ、「AIで案を提案」を押します。

保存動作: 原本は保存しません。JPEGプレビューとPDF先頭5ページの抽出テキスト（最大6,000文字）のみメモリに保持し、1時間後に失効します。コンテナ再起動でも消去されます。ブラウザのタブを更新した場合は同じタブ内でアップロードIDを復元します。PDFのAI画像参照は先頭1ページのみ、AIへ渡す画像は最大3件で、それ以外はメタデータと抽出テキストを参照します。公開サーバーにデプロイする場合は先にログイン認証や所有者別データ隔離を実装してください。Docker Composeの既定設定はローカルホスト限定です。

PDFの寸法抽出、図面のトレース、写真からの正確な形状復元、OCR、原本アーカイブは将来の開発対象です。AI推定寸法を実測寸法として使用しないでください。API事業者側のデータ取扱いについても利用規約を確認してください。

## 実装上の制約

- 検索はWikipediaの概要情報に限られます。一次資料・実寸・立面図・構造図・著作権は未検証です。
- **実在駅舎の忠実な3D復元、写真からの自動テクスチャ作成、画像AI生成はまだありません。**
- 現在の展開図は利用者が入力した寸法に基づく**一般的な簡易建物**です。建物名だけで実寸が取得されたり形状が復元されるものではありません。
- スタイル切替は配色・窓の表示等の初期実装です。アニメ風の画像生成は次の段階です。
- 部品の接着構造は試作段階なので、接合検証・追加ののりしろ・組立説明書を改良する必要があります。
- PDFには英語部品名を使います。日本語フォントへの対応は今後行います。

## 次の開発

一次資料の出典台帳、写真・立面図からの形状推定、編集可能な3Dプレビュー、組立強度の確認、印刷モードの充実。

### ディレクトリ

- app/main.py: FastAPI
- app/research.py: 公開資料検索
- app/ai.py: 各社AI APIと同意時の参考画像送信
- app/uploads.py: 参考資料の検証、縮小プレビュー、一時保管、削除
- app/generator.py: 寸法計算・図面出力
- app/senrolab.py: SenroLab 向けの展開図API（/v1/nets）
- app/static/: Web画面
- tests/: 動作確認
