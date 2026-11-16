# 展開図APIのイメージ。依存パッケージなし（Node 22 の標準機能だけ）。
FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY package.json ./
COPY src ./src
USER node
EXPOSE 8080
# 応答できるか（docker ps の STATUS に healthy と出る）
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/health >/dev/null || exit 1
# PAPERCRAFT_API_TOKEN を渡すと、POST /v1/nets に Bearer トークンを求める
CMD ["node", "src/server.mjs"]
