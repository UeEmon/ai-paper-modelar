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

## 起動方法

Docker Desktopを起動したら、リポジトリ直下で:

    cp .env.example .env
    docker compose up -d --build

ブラウザで http://localhost:8086 を開きます。API定義は http://localhost:8086/docs です。
停止コマンド:

    docker compose down

AI APIを使う場合は .env に AI_PROVIDER=openai と OPENAI_API_KEY=your-key などを設定してください。GeminiならAI_PROVIDER=gemini / GEMINI_API_KEY、AnthropicならAI_PROVIDER=anthropic / ANTHROPIC_API_KEYを使います。
モデル名は OPENAI_MODEL / GEMINI_MODEL / ANTHROPIC_MODEL で変更できます。APIキーをコミットしないでください。

## テスト

    python -m pip install -r requirements-dev.txt
    pytest -q

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
- app/ai.py: 各社AI API
- app/generator.py: 寸法計算・図面出力
- app/static/: Web画面
- tests/: 動作確認
