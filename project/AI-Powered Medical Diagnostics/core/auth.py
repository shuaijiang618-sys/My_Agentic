"""
API Key 鉴权 — 网关式 Bearer Token + 角色 + 租户。

设计目标（最小改造，/chat 主链路不变）：
  - AUTH_ENABLED=false：与 POC 行为一致，不要求 Token
  - AUTH_ENABLED=true：Bearer API Key；管理接口需 admin；RAG 按 tenant 隔离

Key 格式（AUTH_API_KEYS，逗号分隔）：
  <secret>:<role>:<tenant>[:<user_id>]

示例：
  chat-hospital-a:chat:hospital_a
  chat-user-u1:chat:hospital_a:u1
  admin-master:admin:*
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from fastapi import Header, HTTPException, Request


@dataclass(frozen=True)
class AuthContext:
    """已验证的调用方上下文。"""

    role: str
    tenant_id: str
    user_id: Optional[str] = None
    key_hint: str = ""
    auth_source: str = "anonymous"  # anonymous | api_key | jwt

    def effective_user_id(self, client_user_id: str) -> str:
        """
        记忆 / Skills 分桶用的 user_id。
        启用鉴权时加 tenant 前缀，避免跨租户碰撞。
        """
        raw = (self.user_id or client_user_id or "anonymous").strip() or "anonymous"
        if not auth_enabled():
            return raw
        return f"{self.tenant_id}:{raw}"

    def can_access_tenant(self, tenant_id: str) -> bool:
        if self.role == "admin" and self.tenant_id == "*":
            return True
        return self.tenant_id == tenant_id

    def resolve_tenant(self, header_tenant: Optional[str]) -> str:
        """admin 可通过 X-Tenant-ID 指定目标租户。"""
        if header_tenant and self.role == "admin" and self.tenant_id == "*":
            return header_tenant.strip()
        return self.tenant_id


@dataclass(frozen=True)
class _ApiKeyRecord:
    secret: str
    role: str
    tenant_id: str
    user_id: Optional[str] = None


_ROLE_RANK = {"readonly": 1, "chat": 2, "admin": 3}
_VALID_ROLES = set(_ROLE_RANK)
_DEFAULT_PUBLIC_PATHS = {"/health", "/metrics", "/", "/docs", "/openapi.json", "/redoc"}


def auth_enabled() -> bool:
    return _env_bool("AUTH_ENABLED", default=False)


def auth_bind_user_id() -> bool:
    """Key 绑定了 user_id 时，拒绝客户端伪造其它 user_id。"""
    return _env_bool("AUTH_BIND_USER_ID", default=True)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def default_tenant_id() -> str:
    return os.getenv("AUTH_DEFAULT_TENANT", "default").strip() or "default"


def public_paths() -> Set[str]:
    extra = os.getenv("AUTH_PUBLIC_PATHS", "")
    paths = set(_DEFAULT_PUBLIC_PATHS)
    for part in extra.split(","):
        p = part.strip()
        if p:
            paths.add(p if p.startswith("/") else f"/{p}")
    return paths


def _parse_api_keys(raw: str) -> List[_ApiKeyRecord]:
    records: List[_ApiKeyRecord] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) < 3:
            raise ValueError(f"AUTH_API_KEYS 格式错误（需 key:role:tenant[:user]）: {item[:20]}...")
        secret, role, tenant = parts[0].strip(), parts[1].strip(), parts[2].strip()
        user_id = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
        if role not in _VALID_ROLES:
            raise ValueError(f"未知 role: {role!r}，允许 {_VALID_ROLES}")
        if not secret:
            raise ValueError("AUTH_API_KEYS 中存在空 secret")
        records.append(_ApiKeyRecord(secret=secret, role=role, tenant_id=tenant, user_id=user_id))
    return records


def load_api_keys() -> Dict[str, _ApiKeyRecord]:
    raw = os.getenv("AUTH_API_KEYS", "").strip()
    if not raw:
        return {}
    records = _parse_api_keys(raw)
    return {r.secret: r for r in records}


def _key_hint(secret: str) -> str:
    digest = hashlib.sha256(secret.encode()).hexdigest()
    return digest[:8]


def verify_api_key(token: str) -> AuthContext:
    keys = load_api_keys()
    if not keys:
        raise HTTPException(
            503,
            "AUTH_ENABLED=true 但未配置 AUTH_API_KEYS",
        )
    record = keys.get(token)
    if record is None:
        raise HTTPException(401, "无效 API Key")
    return AuthContext(
        role=record.role,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        key_hint=_key_hint(token),
        auth_source="api_key",
    )


def verify_bearer_token(token: str) -> AuthContext:
    """
    校验 Bearer Token：JWT 形态优先走 JWT；否则走 API Key。
    JWT 校验失败且 token 形如 JWT 时不回退到 API Key。
    """
    from core.jwt_auth import JwtAuthError, jwt_enabled, verify_jwt_token

    looks_jwt = token.count(".") == 2
    has_api_keys = bool(load_api_keys())

    if jwt_enabled() and looks_jwt:
        try:
            role, tenant_id, user_id, key_hint = verify_jwt_token(token)
            return AuthContext(
                role=role,
                tenant_id=tenant_id,
                user_id=user_id,
                key_hint=key_hint,
                auth_source="jwt",
            )
        except JwtAuthError as ex:
            raise HTTPException(401, f"无效 JWT: {ex}") from ex

    if has_api_keys:
        return verify_api_key(token)

    if jwt_enabled() and not looks_jwt:
        raise HTTPException(401, "需要 JWT 或 API Key")

    raise HTTPException(
        503,
        "AUTH_ENABLED=true 但未配置 AUTH_API_KEYS 或 AUTH_JWT_SECRET/JWKS",
    )


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, cred = authorization.partition(" ")
    if scheme.lower() != "bearer" or not cred.strip():
        return None
    return cred.strip()


def _anonymous_context() -> AuthContext:
    return AuthContext(
        role="chat",
        tenant_id=default_tenant_id(),
        user_id=None,
        key_hint="",
        auth_source="anonymous",
    )


def _require_role(ctx: AuthContext, min_role: str) -> None:
    if _ROLE_RANK.get(ctx.role, 0) < _ROLE_RANK.get(min_role, 99):
        raise HTTPException(403, f"需要 {min_role} 权限")


def resolve_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> AuthContext:
    """解析当前请求的鉴权上下文（未启用鉴权时返回匿名上下文）。"""
    if not auth_enabled():
        return _anonymous_context()

    path = request.url.path
    if path in public_paths():
        return _anonymous_context()

    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(401, "缺少 Authorization: Bearer <token>")
    return verify_bearer_token(token)


def require_chat_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> AuthContext:
    ctx = resolve_auth(request, authorization)
    if not auth_enabled():
        return ctx
    _require_role(ctx, "chat")
    return ctx


def require_admin_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> AuthContext:
    ctx = resolve_auth(request, authorization)
    if not auth_enabled():
        return ctx
    _require_role(ctx, "admin")
    if x_tenant_id:
        if not ctx.can_access_tenant(x_tenant_id):
            raise HTTPException(403, "无权操作该租户")
        return AuthContext(
            role=ctx.role,
            tenant_id=x_tenant_id.strip(),
            user_id=ctx.user_id,
            key_hint=ctx.key_hint,
            auth_source=ctx.auth_source,
        )
    if ctx.tenant_id == "*":
        ctx = AuthContext(
            role=ctx.role,
            tenant_id=default_tenant_id(),
            user_id=ctx.user_id,
            key_hint=ctx.key_hint,
            auth_source=ctx.auth_source,
        )
    return ctx


def require_readonly_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> AuthContext:
    ctx = resolve_auth(request, authorization)
    if not auth_enabled():
        return ctx
    _require_role(ctx, "readonly")
    return ctx


def validate_client_user_id(ctx: AuthContext, client_user_id: str) -> None:
    """JWT sub 或 Key 绑定 user_id 时校验客户端未伪造。"""
    if not auth_enabled() or not auth_bind_user_id():
        return
    if not ctx.user_id:
        return
    client = (client_user_id or "anonymous").strip() or "anonymous"
    if ctx.auth_source == "jwt" and client in {"anonymous", ctx.user_id}:
        return
    if client != ctx.user_id:
        raise HTTPException(403, "user_id 与 Token 身份不一致")
