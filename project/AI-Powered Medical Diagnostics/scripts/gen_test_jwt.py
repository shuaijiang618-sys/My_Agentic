#!/usr/bin/env python3
"""内测：签发 HS256 JWT（读取 .env 中 AUTH_JWT_*）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="签发测试用 HS256 JWT")
    parser.add_argument("--sub", default="u1", help="JWT sub / user_id")
    parser.add_argument("--tenant", default="default", help="tenant_id claim")
    parser.add_argument(
        "--roles",
        default="chat",
        help="逗号分隔角色，如 chat,admin",
    )
    parser.add_argument("--expires", type=int, default=3600, help="有效期（秒）")
    parser.add_argument("--print-curl", action="store_true", help="输出 /chat curl 示例")
    args = parser.parse_args()

    from core.jwt_auth import mint_hs256_token

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    token = mint_hs256_token(
        sub=args.sub,
        tenant_id=args.tenant,
        roles=roles,
        expires_in_s=args.expires,
    )
    print(token)
    if args.print_curl:
        host = "127.0.0.1:8010"
        print(
            f'\ncurl -s -X POST http://{host}/chat '
            f'-H "Authorization: Bearer {token}" '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"message":"你好"}}\'',
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
