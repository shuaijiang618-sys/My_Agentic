"""
JWT / OIDC Bearer 校验 — 与 API Key 并存。

支持：
  - HS256（AUTH_JWT_SECRET，本地/内测）
  - RS256 + JWKS（AUTH_JWT_JWKS_URL，OIDC 提供方）

Claims 映射（均可通过 env 覆盖）：
  sub          → user_id
  tenant_id    → tenant（缺省 AUTH_DEFAULT_TENANT）
  roles / realm_access.roles → 映射为 chat | readonly | admin
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ROLE_RANK = {"readonly": 1, "chat": 2, "admin": 3}
_VALID_ROLES = set(_ROLE_RANK)


class JwtAuthError(Exception):
    """JWT 校验失败。"""


def jwt_enabled() -> bool:
    raw = os.getenv("AUTH_JWT_ENABLED")
    if raw is not None:
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(os.getenv("AUTH_JWT_SECRET", "").strip() or os.getenv("AUTH_JWT_JWKS_URL", "").strip())


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _parse_algorithms() -> List[str]:
    raw = _env("AUTH_JWT_ALGORITHMS", "HS256")
    algs = [a.strip() for a in raw.split(",") if a.strip()]
    return algs or ["HS256"]


def _parse_role_map() -> Dict[str, str]:
    """
    AUTH_JWT_ROLE_MAP=admin:admin,viewer:readonly,doctor:chat
    未命中映射时，若 claim 值本身为合法 role 则直接使用。
    """
    raw = _env("AUTH_JWT_ROLE_MAP")
    mapping: Dict[str, str] = {}
    if not raw:
        return mapping
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        src, dst = pair.split(":", 1)
        src, dst = src.strip().lower(), dst.strip().lower()
        if src and dst in _VALID_ROLES:
            mapping[src] = dst
    return mapping


def _normalize_roles(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [p.strip().lower() for p in raw.replace("|", ",").split(",") if p.strip()]
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip().lower())
        return out
    return []


def _extract_roles(payload: Dict[str, Any]) -> List[str]:
    roles_claim = _env("AUTH_JWT_ROLES_CLAIM", "roles")
    roles = _normalize_roles(payload.get(roles_claim))
    if roles:
        return roles
    realm = payload.get("realm_access")
    if isinstance(realm, dict):
        roles = _normalize_roles(realm.get("roles"))
        if roles:
            return roles
    scope = payload.get("scope")
    if isinstance(scope, str):
        return [s.strip().lower() for s in scope.split() if s.strip()]
    return []


def resolve_role_from_claims(payload: Dict[str, Any]) -> str:
    role_map = _parse_role_map()
    roles = _extract_roles(payload)
    best = "chat"
    for role in roles:
        mapped = role_map.get(role, role)
        if mapped not in _VALID_ROLES:
            continue
        if _ROLE_RANK[mapped] >= _ROLE_RANK[best]:
            best = mapped
    return best


def _claim_scalar(value: Any) -> Optional[str]:
    """Keycloak 等 IdP 常把自定义 attribute 写成字符串数组。"""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_tenant_from_claims(payload: Dict[str, Any]) -> str:
    claim = _env("AUTH_JWT_TENANT_CLAIM", "tenant_id")
    value = _claim_scalar(payload.get(claim))
    if value:
        return value
    org = _claim_scalar(payload.get("org_id"))
    if org:
        return org
    from core.auth import default_tenant_id
    return default_tenant_id()


def resolve_user_from_claims(payload: Dict[str, Any]) -> Optional[str]:
    claim = _env("AUTH_JWT_SUB_CLAIM", "sub")
    preferred = _env("AUTH_JWT_USERNAME_CLAIM", "preferred_username")
    value = _claim_scalar(payload.get(claim))
    if value:
        return value
    return _claim_scalar(payload.get(preferred))


def _decode_options() -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_aud": bool(_env("AUTH_JWT_AUDIENCE")),
        "verify_iss": bool(_env("AUTH_JWT_ISSUER")),
    }
    if _env_bool("AUTH_JWT_VERIFY_EXP", default=True) is False:
        opts["verify_exp"] = False
    return opts


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


_jwks_client = None
_jwks_url_loaded = ""


def _import_pyjwt():
    try:
        import jwt
        return jwt
    except ImportError as ex:
        raise JwtAuthError(
            "缺少 PyJWT。请执行: .venv/bin/python -m pip install 'PyJWT[crypto]==2.10.1'"
        ) from ex


def _get_jwks_client(url: str):
    global _jwks_client, _jwks_url_loaded
    if _jwks_client is not None and _jwks_url_loaded == url:
        return _jwks_client
    _import_pyjwt()
    from jwt import PyJWKClient

    _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
    _jwks_url_loaded = url
    return _jwks_client


def _looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2


def verify_jwt_token(token: str) -> Tuple[str, str, Optional[str], str]:
    """
    校验 JWT，返回 (role, tenant_id, user_id, key_hint)。
    key_hint 用于审计（sub 前 8 位或 jti）。
    """
    if not jwt_enabled():
        raise JwtAuthError("JWT 未启用")

    jwt = _import_pyjwt()

    algorithms = _parse_algorithms()
    options = _decode_options()
    decode_kwargs: Dict[str, Any] = {"algorithms": algorithms, "options": options}

    audience = _env("AUTH_JWT_AUDIENCE")
    issuer = _env("AUTH_JWT_ISSUER")
    if audience:
        decode_kwargs["audience"] = audience
    if issuer:
        decode_kwargs["issuer"] = issuer

    jwks_url = _env("AUTH_JWT_JWKS_URL")
    secret = _env("AUTH_JWT_SECRET")

    try:
        if jwks_url:
            client = _get_jwks_client(jwks_url)
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, **decode_kwargs)
        elif secret:
            payload = jwt.decode(token, secret, **decode_kwargs)
        else:
            raise JwtAuthError("需配置 AUTH_JWT_SECRET 或 AUTH_JWT_JWKS_URL")
    except jwt.PyJWTError as ex:
        raise JwtAuthError(str(ex)) from ex

    if not isinstance(payload, dict):
        raise JwtAuthError("JWT payload 无效")

    role = resolve_role_from_claims(payload)
    tenant_id = resolve_tenant_from_claims(payload)
    user_id = resolve_user_from_claims(payload)
    hint_source = user_id or str(payload.get("jti", "")) or token[:12]
    key_hint = f"jwt:{hint_source[:8]}"
    return role, tenant_id, user_id, key_hint


def mint_hs256_token(
    *,
    sub: str,
    tenant_id: str = "default",
    roles: Optional[List[str]] = None,
    expires_in_s: int = 3600,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """内测用：签发 HS256 JWT（需 AUTH_JWT_SECRET）。"""
    jwt = _import_pyjwt()

    secret = _env("AUTH_JWT_SECRET")
    if not secret:
        raise ValueError("AUTH_JWT_SECRET 未配置")

    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": roles or ["chat"],
        "iat": now,
        "exp": now + expires_in_s,
    }
    audience = _env("AUTH_JWT_AUDIENCE")
    issuer = _env("AUTH_JWT_ISSUER")
    if audience:
        payload["aud"] = audience
    if issuer:
        payload["iss"] = issuer
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")
