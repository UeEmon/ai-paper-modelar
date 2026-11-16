# ai-paper-modelar

Nゲージ（1/150）のペーパークラフトの展開図を作るAPIです。
SenroLab（UeEmon/Nine-Gage-Systems）の「再現してみた」で作った仮オブジェクト（トンネル・鉄橋・駅舎など、実在の製品にない物）の種類と寸法を受け取り、実寸で印刷できるSVG（用紙1枚ずつ）を返します。

- API の仕様: [docs/senrolab/README.md](docs/senrolab/README.md)・[docs/senrolab/openapi.yaml](docs/senrolab/openapi.yaml)
- 依存パッケージなし（Node 22 の標準機能だけ）

## 動かす

```sh
npm start                       # http://localhost:8080
PAPERCRAFT_API_TOKEN=xxxx npm start   # POST /v1/nets に Bearer トークンを求める
npm test
```

## 作る展開図

| 種類 | 展開図 |
| --- | --- |
| tunnel | 覆い（側壁・天井・側壁の帯）と、アーチ形の穴のある坑口2枚。内側の高さは30mm以上にする |
| bridge | トラス模様の側面のけた2枚と床 |
| viaduct | アーチ模様の側面2枚と床 |
| station・building・landmark・other | 4面の壁の帯（窓の模様）と屋根 |
| platform | 4面の帯と上面 |
| mountain | 四角錐台（上面と4枚の斜面） |
| water | 波の模様の板 |

用紙より長い部品は、折り線の所（長すぎれば等分）で分け、貼り合わせるのりしろを付けます。

## 置き方

CI が main とタグ `v*` で `ghcr.io/ueemon/ai-paper-modelar` にイメージ（arm64）を置きます。Oracle Cloud では専用VM `papercraft-1` で動かします（UeEmon/oracle-cloud-deploy の `papercraft/`）。インターネットには公開せず、SenroLab のVMからだけ届くようにします。
