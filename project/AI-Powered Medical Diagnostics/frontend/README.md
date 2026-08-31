# Medical Diagnostics Frontend

Vue 3 + Vite 调试台，参照 [EchoMindFrontend-main](../../EchoMind/EchoMindFrontend-main)，仅对接 **AI-Powered Medical Diagnostics**（8010）。

## 功能

- 对话 `/chat`（展示 sources、blocked、emergency）
- RAG 检索 `/search`
- 知识库添加 / 批量导入（admin Token + `X-Tenant-ID`）
- Keycloak Password Grant 一键取 JWT
- Bearer Token 持久化（localStorage）

## 快速启动

```bash
# 首次安装（若镜像源报错，可加 --registry=https://registry.npmjs.org/）
npm install

# 终端 1：后端
cd ..
./scripts/start.sh

# 终端 2：前端
chmod +x ../scripts/start_frontend.sh
../scripts/start_frontend.sh
# → http://localhost:5173
```

开发环境默认将 `/api/*` 代理到 `http://127.0.0.1:8010`。

### 鉴权开启时

1. 侧栏点击 **获取 JWT**（Keycloak `doctor` / `doctor123`），或粘贴 API Key
2. 再发送消息

`.env`（可选）：

```bash
cp .env.example .env
```

## 构建与 Docker

```bash
npm run build
docker compose up --build
# → http://localhost:5174
```

## 目录

```
frontend/
├── src/App.vue       # 主界面
├── src/lib/api.js    # API 封装 + Keycloak Token
├── vite.config.js    # /api → 8010 代理
└── docker/nginx.conf
```
