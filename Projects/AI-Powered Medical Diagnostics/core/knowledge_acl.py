"""知识库租户 ACL — 纯逻辑，无 Chroma 依赖。"""
from __future__ import annotations

from typing import Any, Dict, Optional


def build_tenant_where(
    tenant_id: Optional[str],
    doc_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """租户隔离：可见本租户 + shared；未传 tenant 时不做租户过滤。"""
    if not tenant_id:
        return {"doc_type": doc_type} if doc_type else None
    tenant_clause: Dict[str, Any] = {
        "$or": [{"tenant_id": tenant_id}, {"tenant_id": "shared"}],
    }
    if doc_type:
        return {"$and": [tenant_clause, {"doc_type": doc_type}]}
    return tenant_clause
