# -*- coding: utf-8 -*-
"""鉴权模块单元回归（无需启动服务）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List
import os

from core.auth import (
    AuthContext,
    _parse_api_keys,
    auth_bind_user_id,
    auth_enabled,
    default_tenant_id,
)
from core.knowledge_acl import build_tenant_where


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str


def _run(name: str, fn: Callable[[], bool], detail: str = "") -> CaseResult:
    try:
        ok = fn()
        return CaseResult(name=name, passed=ok, detail=detail if ok else detail or "断言失败")
    except Exception as ex:
        return CaseResult(name=name, passed=False, detail=str(ex))


def run_auth_suite() -> List[CaseResult]:
    results: List[CaseResult] = []

    results.append(_run(
        "parse_api_keys",
        lambda: len(_parse_api_keys("k1:chat:tenant_a,k2:admin:*:ops")) == 2,
        "应解析两条 Key",
    ))

    def _verify_key() -> bool:
        from core.auth import verify_api_key
        old = os.environ.get("AUTH_API_KEYS")
        os.environ["AUTH_API_KEYS"] = "secret-chat:chat:hospital_a:u1"
        try:
            ctx = verify_api_key("secret-chat")
            return ctx.tenant_id == "hospital_a" and ctx.user_id == "u1"
        finally:
            if old is None:
                os.environ.pop("AUTH_API_KEYS", None)
            else:
                os.environ["AUTH_API_KEYS"] = old

    results.append(_run("verify_valid_key", _verify_key, "应验证有效 Key"))

    def _effective_user_id() -> bool:
        old = os.environ.get("AUTH_ENABLED")
        try:
            os.environ["AUTH_ENABLED"] = "false"
            plain = AuthContext(role="chat", tenant_id="t1", user_id="u1").effective_user_id("u1")
            os.environ["AUTH_ENABLED"] = "true"
            prefixed = AuthContext(role="chat", tenant_id="t1", user_id="u1").effective_user_id("u1")
            return plain == "u1" and prefixed == "t1:u1"
        finally:
            if old is None:
                os.environ.pop("AUTH_ENABLED", None)
            else:
                os.environ["AUTH_ENABLED"] = old

    results.append(_run("effective_user_id_prefixed", _effective_user_id, "启用鉴权时加 tenant 前缀"))

    results.append(_run(
        "tenant_where_shared",
        lambda: build_tenant_where("hospital_a") == {
            "$or": [{"tenant_id": "hospital_a"}, {"tenant_id": "shared"}],
        },
        "检索应包含 shared 租户",
    ))

    results.append(_run(
        "auth_disabled_by_default",
        lambda: not auth_enabled(),
        "默认 AUTH_ENABLED=false",
    ))

    results.append(_run(
        "bind_user_default_on",
        lambda: auth_bind_user_id(),
        "默认 AUTH_BIND_USER_ID=true",
    ))

    results.append(_run(
        "default_tenant",
        lambda: default_tenant_id() == "default",
        "默认租户 default",
    ))

    def _jwt_roundtrip() -> bool:
        from core.jwt_auth import mint_hs256_token, verify_jwt_token
        old = {
            k: os.environ.get(k)
            for k in ("AUTH_JWT_SECRET", "AUTH_JWT_AUDIENCE", "AUTH_JWT_ISSUER")
        }
        try:
            os.environ["AUTH_JWT_SECRET"] = "test-secret-for-auth-runner"
            os.environ.pop("AUTH_JWT_AUDIENCE", None)
            os.environ.pop("AUTH_JWT_ISSUER", None)
            token = mint_hs256_token(sub="u99", tenant_id="hospital_a", roles=["admin", "chat"])
            role, tenant, user, hint = verify_jwt_token(token)
            return role == "admin" and tenant == "hospital_a" and user == "u99" and hint.startswith("jwt:")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    results.append(_run("jwt_hs256_roundtrip", _jwt_roundtrip, "HS256 签发与校验"))

    results.append(_run(
        "keycloak_tenant_array_claim",
        lambda: __import__("core.jwt_auth", fromlist=["resolve_tenant_from_claims"]).resolve_tenant_from_claims(
            {"tenant_id": ["hospital_a"]},
        ) == "hospital_a",
        "Keycloak tenant_id 数组 claim",
    ))

    return results


def run_all() -> dict:
    cases = run_auth_suite()
    passed = sum(1 for c in cases if c.passed)
    return {
        "suite": "auth",
        "passed": passed,
        "total": len(cases),
        "ok": passed == len(cases),
        "cases": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in cases],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))
