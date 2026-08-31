#!/usr/bin/env python3
"""批量导入 data/medical_knowledge 到 ChromaDB。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def _build_auth_headers(api_key: str | None, tenant_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Powered Medical Diagnostics 知识库批量导入")
    parser.add_argument(
        "--dir",
        default=str(ROOT / "data" / "medical_knowledge"),
        help="知识库根目录",
    )
    parser.add_argument(
        "--via-api",
        metavar="URL",
        help="通过运行中的 API 导入，例如 http://127.0.0.1:8010",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MEDICAL_API_KEY") or os.getenv("AUTH_API_KEY") or "",
        help="Bearer Token（API Key 或 JWT）；也可设 env MEDICAL_API_KEY",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("AUTH_TENANT_ID") or os.getenv("MEDICAL_TENANT_ID") or "",
        help="admin 写入目标租户（X-Tenant-ID）；也可设 env AUTH_TENANT_ID",
    )
    parser.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    args = parser.parse_args()

    directory = str(Path(args.dir).resolve())
    recursive = not args.no_recursive
    api_key = (args.api_key or "").strip() or None
    tenant_id = (args.tenant_id or "").strip() or None

    if args.via_api:
        import httpx

        url = args.via_api.rstrip("/") + "/knowledge/import"
        headers = _build_auth_headers(api_key, tenant_id)
        resp = httpx.post(
            url,
            json={"directory": directory, "recursive": recursive},
            headers=headers,
            timeout=120.0,
        )
        if resp.status_code == 401:
            print(
                "401 未授权：请设置 --api-key 或 env MEDICAL_API_KEY（admin Key/JWT）",
                file=sys.stderr,
            )
        resp.raise_for_status()
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
        return 0

    from mcp.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", str(ROOT / "data" / "chroma")),
    )
    tenant = tenant_id or os.getenv("AUTH_DEFAULT_TENANT", "shared")
    result = kb.import_from_directory(directory, recursive=recursive, tenant_id=tenant)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
