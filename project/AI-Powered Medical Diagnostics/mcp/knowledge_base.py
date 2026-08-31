"""
医疗 RAG 知识库 — 公开医学科普、科室说明、检查项目、就诊流程。
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb

logger = logging.getLogger(__name__)


class KnowledgeBase:
    COLLECTION_NAME = "medical_knowledge_base"

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
    ):
        try:
            self._client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            self._client.heartbeat()
            logger.info("医疗知识库 ChromaDB: %s:%s", chroma_host, chroma_port)
        except Exception:
            logger.info("ChromaDB 不可用，使用本地: %s", chroma_path)
            self._client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )

        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "AI-Powered Medical Diagnostics RAG"},
        )
        if self._collection.count() == 0:
            self._load_default_docs()

    def add_documents(
        self,
        documents: List[Dict[str, str]],
        *,
        upsert: bool = True,
        tenant_id: str = "shared",
    ) -> int:
        ids, docs, metas = [], [], []
        for doc in documents:
            title = doc.get("title", "")
            content = doc.get("content", "")
            doc_type = doc.get("doc_type", "popular_science")
            source = doc.get("source", "internal")
            doc_tenant = doc.get("tenant_id", tenant_id) or tenant_id
            for i, chunk in enumerate(self._chunk_text(content)):
                doc_id = hashlib.md5(
                    f"{doc_tenant}_{title}_{i}_{chunk[:40]}".encode(),
                ).hexdigest()
                ids.append(doc_id)
                docs.append(chunk)
                metas.append({
                    "title": title,
                    "doc_type": doc_type,
                    "source": source,
                    "chunk_index": i,
                    "tenant_id": doc_tenant,
                })
        if ids:
            if upsert and hasattr(self._collection, "upsert"):
                self._collection.upsert(ids=ids, documents=docs, metadatas=metas)
            else:
                self._collection.add(ids=ids, documents=docs, metadatas=metas)
        return len(ids)

    def import_from_directory(
        self,
        root_dir: str,
        *,
        recursive: bool = True,
        tenant_id: str = "shared",
    ) -> Dict[str, Any]:
        """批量导入目录下的 md/txt/json/jsonl。"""
        from mcp.knowledge_importer import load_documents_from_directory

        documents, errors = load_documents_from_directory(
            Path(root_dir), recursive=recursive,
        )
        if not documents and errors:
            return {"added_chunks": 0, "total": self.doc_count, "errors": errors}
        added = self.add_documents(documents, tenant_id=tenant_id) if documents else 0
        return {
            "added_chunks": added,
            "document_count": len(documents),
            "total": self.doc_count,
            "tenant_id": tenant_id,
            "errors": errors,
        }

    def stats(self) -> Dict[str, Any]:
        """知识库片段总数（按类型统计需全量 scan，此处返回总数）。"""
        return {"chunk_count": self.doc_count, "collection": self.COLLECTION_NAME}

    def backfill_tenant_shared(self, *, default_tenant: str = "shared") -> Dict[str, Any]:
        """
        为缺少 tenant_id 的历史片段补打 default_tenant（通常 shared）。
        启用多租户 RAG 后，旧数据否则无法被 $or tenant 过滤命中。
        """
        batch = self._collection.get(include=["metadatas"])
        ids: List[str] = []
        metas: List[Dict[str, Any]] = []
        for doc_id, meta in zip(batch.get("ids") or [], batch.get("metadatas") or []):
            if not meta or meta.get("tenant_id"):
                continue
            updated = dict(meta)
            updated["tenant_id"] = default_tenant
            ids.append(doc_id)
            metas.append(updated)
        if ids:
            self._collection.update(ids=ids, metadatas=metas)
            logger.info("已回填 tenant_id=%s 的片段 %d 条", default_tenant, len(ids))
        return {
            "updated_chunks": len(ids),
            "default_tenant": default_tenant,
            "total": self.doc_count,
        }

    @staticmethod
    def _tenant_where(
        tenant_id: Optional[str],
        doc_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        from core.knowledge_acl import build_tenant_where
        return build_tenant_where(tenant_id, doc_type)

    def search(
        self,
        query: str,
        top_k: int = 5,
        doc_type: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where = self._tenant_where(tenant_id, doc_type)
        kwargs: Dict[str, Any] = {"query_texts": [query], "n_results": top_k}
        if where:
            kwargs["where"] = where
        try:
            results = self._collection.query(**kwargs)
        except Exception:
            results = self._collection.query(query_texts=[query], n_results=top_k)

        items: List[Dict[str, Any]] = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                meta_tenant = meta.get("tenant_id") or "shared"
                if tenant_id and meta_tenant not in {tenant_id, "shared"}:
                    continue
                items.append({
                    "title": meta.get("title", ""),
                    "content": doc,
                    "doc_type": meta.get("doc_type", ""),
                    "source": meta.get("source", ""),
                    "tenant_id": meta_tenant,
                    "score": round(1.0 - dist, 4),
                    "chunk": meta.get("chunk_index", 0),
                })
        return items[:top_k]

    @property
    def doc_count(self) -> int:
        return self._collection.count()

    async def search_handler(self, params: Dict[str, Any], context: Any) -> List[Dict]:
        ctx = context if isinstance(context, dict) else {}
        tenant_id = params.get("tenant_id") or ctx.get("tenant_id")
        return self.search(
            params.get("query", ""),
            top_k=int(params.get("top_k", 5)),
            doc_type=params.get("doc_type"),
            tenant_id=tenant_id,
        )

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        if len(text) <= chunk_size:
            return [text] if text.strip() else []
        chunks: List[str] = []
        current = ""
        for sent in text.replace("\n", "。").split("。"):
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > chunk_size:
                if current:
                    chunks.append(current)
                current = sent
            else:
                current = f"{current}。{sent}" if current else sent
        if current:
            chunks.append(current)
        return chunks

    def _load_default_docs(self) -> None:
        docs = [
            {
                "title": "消化内科导诊",
                "doc_type": "department",
                "source": "医院科室说明（示例）",
                "content": (
                    "消化内科常见就诊症状：腹痛、腹胀、恶心、呕吐、腹泻、便秘、"
                    "反酸、烧心、黑便、黄疸等。"
                    "若伴有剧烈腹痛、持续呕吐无法进食、便血量大，应优先挂急诊。"
                    "初诊可携带近期体检或化验报告。"
                ),
            },
            {
                "title": "呼吸内科导诊",
                "doc_type": "department",
                "source": "医院科室说明（示例）",
                "content": (
                    "呼吸内科常见：咳嗽、咳痰、胸闷、气喘、发热伴呼吸道症状。"
                    "若出现呼吸困难、口唇发紫、胸痛，请立即急诊。"
                ),
            },
            {
                "title": "ALT 丙氨酸氨基转移酶",
                "doc_type": "lab_item",
                "source": "公开医学科普（示例）",
                "content": (
                    "ALT 主要反映肝细胞损伤。轻度升高可见于脂肪肝、饮酒、药物影响、"
                    "病毒性肝炎等。需结合 AST、胆红素、超声等进一步评估。"
                    "单次轻度升高不一定代表严重肝病，建议复查并咨询消化内科或肝病专科。"
                ),
            },
            {
                "title": "挂号与分诊流程",
                "doc_type": "hospital_flow",
                "source": "就诊流程（示例）",
                "content": (
                    "门诊流程：预约/现场挂号 → 分诊台报到 → 候诊 → 医生面诊 → 检查/取药。"
                    "不确定科室时可使用医院导诊台或官方导诊服务。"
                    "急诊适用于突发严重症状，无需预约。"
                ),
            },
            {
                "title": "血压指标科普",
                "doc_type": "popular_science",
                "source": "公开医学科普（示例）",
                "content": (
                    "血压包含收缩压与舒张压。单次测量偏高可能受情绪、测量姿势影响。"
                    "建议不同日复测；持续升高应咨询心内科。"
                    "出现胸痛、呼吸困难、意识改变等请急诊。"
                ),
            },
        ]
        self.add_documents(docs, tenant_id="shared")
        logger.info("已导入默认医疗知识库 %d 篇（tenant=shared）", len(docs))
