# Keycloak 本地联调

与 **AI-Powered Medical Diagnostics** API 的 OIDC/JWT 联调环境。启动后自动导入 `medical` realm。

## 前置

- Docker Desktop（或 Docker Engine + Compose v2）
- 项目 API 依赖已安装（`pip install -r requirements.txt`）

## 1. 启动 Keycloak

```bash
./scripts/keycloak_up.sh
```

| 项 | 值 |
|----|-----|
| Admin Console | http://localhost:8080/admin |
| Admin 账号 | `admin` / `admin` |
| Realm | `medical` |
| Client ID | `medical-api`（public，Direct Access Grants 已开） |
| OIDC Discovery | http://localhost:8080/realms/medical/.well-known/openid-configuration |
| JWKS | http://localhost:8080/realms/medical/protocol/openid-connect/certs |

### 预置测试用户

| 用户 | 密码 | Realm Role | tenant_id |
|------|------|------------|-----------|
| `doctor` | `doctor123` | `md-chat` | `hospital_a` |
| `kbadmin` | `kbadmin123` | `md-admin` | `hospital_a` |
| `viewer` | `viewer123` | `md-readonly` | `hospital_a` |

Role 映射（在 API `.env` 中）：

```bash
AUTH_JWT_ROLE_MAP=md-chat:chat,md-admin:admin,md-readonly:readonly
```

## 2. 配置医疗 API

将 Keycloak 相关变量合并进项目根 `.env`：

```bash
cat docker/keycloak/.env.example >> .env
# 或手动复制 AUTH_JWT_* 段
```

关键变量：

```bash
AUTH_ENABLED=true
AUTH_JWT_ENABLED=true
AUTH_JWT_ISSUER=http://localhost:8080/realms/medical
AUTH_JWT_JWKS_URL=http://localhost:8080/realms/medical/protocol/openid-connect/certs
AUTH_JWT_ALGORITHMS=RS256
AUTH_JWT_AUDIENCE=medical-api
AUTH_JWT_ROLE_MAP=md-chat:chat,md-admin:admin,md-readonly:readonly
```

重启 API：

```bash
./scripts/start.sh
```

## 3. 获取 Token 并调用

```bash
# 获取 doctor 的 access_token
./scripts/keycloak_token.sh doctor doctor123

# 一键联调（Token + /chat）
./scripts/keycloak_smoke.sh

# 手动 curl
TOKEN=$(./scripts/keycloak_token.sh doctor doctor123)
curl -s -X POST http://127.0.0.1:8010/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"ALT 52 偏高是什么意思？"}' | python3 -m json.tool
```

### admin 导入知识库

```bash
TOKEN=$(./scripts/keycloak_token.sh kbadmin kbadmin123)
./scripts/import_knowledge.sh --via-api http://127.0.0.1:8010 \
  --api-key "$TOKEN" --tenant-id hospital_a
```

## 4. Token 里有什么

Keycloak access token（解码后）大致包含：

```json
{
  "iss": "http://localhost:8080/realms/medical",
  "aud": ["medical-api"],
  "sub": "…uuid…",
  "preferred_username": "doctor",
  "tenant_id": "hospital_a",
  "realm_access": { "roles": ["md-chat", "default-roles-medical"] }
}
```

API 映射逻辑见 `core/jwt_auth.py`：

- `realm_access.roles` → `AUTH_JWT_ROLE_MAP` → `chat` / `admin` / `readonly`
- `tenant_id` claim（User Attribute Mapper）→ RAG 租户隔离
- `sub` / `preferred_username` → 记忆分桶 user_id

## 5. 架构

```
Browser / curl
    │ Password Grant (dev only)
    ▼
Keycloak :8080  ──JWT(RS256)──▶  Medical API :8010
  realm: medical                    AUTH_JWT_JWKS_URL
  client: medical-api               /chat + RAG tenant filter
```

生产环境请改用 **Authorization Code + PKCE**，关闭 Password Grant。

## 6. 故障排查

| 现象 | 处理 |
|------|------|
| `401 无效 JWT` | 核对 `AUTH_JWT_ISSUER` / `JWKS_URL` 与 Keycloak realm 一致 |
| `Invalid audience` | 确认 `AUTH_JWT_AUDIENCE=medical-api`；realm 已含 audience mapper |
| Password Grant 403 | Admin Console → Clients → medical-api → 开启 **Direct access grants** |
| `tenant_id` 缺失 | Users → doctor → Attributes → `tenant_id=hospital_a` |
| Keycloak 启动慢 | 首次 import realm 约 30–60s，`docker compose logs -f` 查看 |

## 7. 停止 / 重置

```bash
cd docker/keycloak
docker compose down          # 停止
docker compose down -v       # 停止并清数据（重新 import realm）
```

## 文件

```
docker/keycloak/
├── docker-compose.yml
├── .env.example          # 复制到项目根 .env
├── import/
│   └── realm-medical.json
└── README.md
```
