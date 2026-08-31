#!/usr/bin/env python3
"""回填知识库 tenant_id=shared，并导入 md 到指定租户。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="1) 旧片段补 tenant_id=shared  2) 导入 knowledge 目录到租户",
    )
    parser.add_argument(
        "--tenant",
        default=os.getenv("AUTH_DEFAULT_TENANT", "hospital_a"),
        help="导入目标租户",
    )
    parser.add_argument(
        "--dir",
        default=str(ROOT / "data" / "medical_knowledge"),
        help="导入目录",
    )
    parser.add_argument(
        "--via-api",
        metavar="URL",
        help="经 API 导入（需 admin JWT/API Key）",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MEDICAL_API_KEY") or os.getenv("AUTH_API_KEY") or "",
    )
    parser.add_argument("--skip-backfill", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args()

    from mcp.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv("CHROMA_PERSIST_DIRECTORY", str(ROOT / "data" / "chroma")),
    )

    report: dict = {"total_before": kb.doc_count}

    if not args.skip_backfill:
        report["backfill"] = kb.backfill_tenant_shared(default_tenant="shared")

    if not args.skip_import:
        directory = str(Path(args.dir).resolve())
        if args.via_api:
            import httpx

            headers: dict[str, str] = {"X-Tenant-ID": args.tenant.strip()}
            if args.api_key.strip():
                headers["Authorization"] = f"Bearer {args.api_key.strip()}"
            resp = httpx.post(
                f"{args.via_api.rstrip('/')}/knowledge/import",
                json={"directory": directory, "recursive": True},
                headers=headers,
                timeout=120.0,
            )
            resp.raise_for_status()
            report["import"] = resp.json()
        else:
            report["import"] = kb.import_from_directory(directory, tenant_id=args.tenant)

    report["total_after"] = kb.doc_count
    q = "ALT 52 偏高是什么意思"
    ha = kb.search(q, top_k=1, tenant_id="hospital_a")
    report["probe_hospital_a"] = ha[0] if ha else None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
