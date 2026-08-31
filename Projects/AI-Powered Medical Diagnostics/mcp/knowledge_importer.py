"""
从目录 / JSON / JSONL 批量加载医疗知识库文档。

支持格式：
  - data/medical_knowledge/<doc_type>/*.md   （可选 YAML front matter）
  - data/medical_knowledge/<doc_type>/*.txt
  - data/medical_knowledge/batch.json        （文档数组）
  - data/medical_knowledge/batch.jsonl       （每行一篇）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_DOC_TYPES = frozenset({
    "popular_science",
    "department",
    "lab_item",
    "hospital_flow",
})

_FOLDER_TYPE_MAP = {
    "departments": "department",
    "department": "department",
    "lab_items": "lab_item",
    "lab_item": "lab_item",
    "hospital_flows": "hospital_flow",
    "hospital_flow": "hospital_flow",
    "popular_science": "popular_science",
    "science": "popular_science",
}


def _split_front_matter(raw: str) -> Tuple[Dict[str, Any], str]:
    text = raw.lstrip()
    if not text.startswith("---"):
        return {}, raw
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    meta: Dict[str, Any] = {}
    end_idx: Optional[int] = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    if end_idx is None:
        return {}, raw
    return meta, "\n".join(lines[end_idx + 1:])


def _normalize_doc(raw: Dict[str, Any], default_type: str = "popular_science") -> Optional[Dict[str, str]]:
    title = str(raw.get("title") or "").strip()
    content = str(raw.get("content") or raw.get("body") or "").strip()
    if not content:
        return None
    if not title:
        title = content[:40].replace("\n", " ")
    doc_type = str(raw.get("doc_type") or default_type).strip()
    if doc_type not in VALID_DOC_TYPES:
        doc_type = default_type if default_type in VALID_DOC_TYPES else "popular_science"
    source = str(raw.get("source") or "batch_import").strip()
    return {
        "title": title,
        "content": content,
        "doc_type": doc_type,
        "source": source,
    }


def _doc_type_from_path(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        if len(rel.parts) >= 2:
            folder = rel.parts[0].lower()
            return _FOLDER_TYPE_MAP.get(folder, "popular_science")
    except ValueError:
        pass
    return "popular_science"


def load_json_file(path: Path) -> List[Dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("documents") or data.get("items") or [data]
    if not isinstance(data, list):
        raise ValueError(f"{path}: JSON 根节点必须是数组或含 documents 字段的对象")
    docs: List[Dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            doc = _normalize_doc(item)
            if doc:
                docs.append(doc)
    return docs


def load_jsonl_file(path: Path) -> List[Dict[str, str]]:
    docs: List[Dict[str, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no} 每行必须是 JSON 对象")
        doc = _normalize_doc(item)
        if doc:
            docs.append(doc)
    return docs


def load_text_file(path: Path, root: Path) -> Optional[Dict[str, str]]:
    raw = path.read_text(encoding="utf-8")
    default_type = _doc_type_from_path(path, root)
    if path.suffix.lower() == ".md":
        meta, body = _split_front_matter(raw)
        merged = {
            "title": meta.get("title") or path.stem,
            "content": body.strip(),
            "doc_type": meta.get("doc_type") or default_type,
            "source": meta.get("source") or str(path.relative_to(root)),
        }
        return _normalize_doc(merged, default_type=default_type)
    return _normalize_doc({
        "title": path.stem,
        "content": raw.strip(),
        "doc_type": default_type,
        "source": str(path.relative_to(root)),
    }, default_type=default_type)


def load_documents_from_directory(
    root_dir: Path,
    *,
    recursive: bool = True,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    扫描目录并返回 (documents, errors)。
    """
    root = root_dir.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"知识库目录不存在: {root}")

    documents: List[Dict[str, str]] = []
    errors: List[str] = []

    # 优先处理 batch.json / batch.jsonl
    for batch_name in ("batch.json", "batch.jsonl"):
        batch_path = root / batch_name
        if not batch_path.exists():
            continue
        try:
            if batch_name.endswith(".jsonl"):
                documents.extend(load_jsonl_file(batch_path))
            else:
                documents.extend(load_json_file(batch_path))
        except Exception as ex:
            errors.append(f"{batch_path}: {ex}")

    pattern = "**/*" if recursive else "*"
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name in {"batch.json", "batch.jsonl", "README.md"}:
            continue
        suffix = path.suffix.lower()
        if suffix not in {".md", ".txt", ".json"}:
            continue
        if suffix == ".json" and path.name == "batch.json":
            continue
        try:
            if suffix == ".json":
                documents.extend(load_json_file(path))
            else:
                doc = load_text_file(path, root)
                if doc:
                    documents.append(doc)
        except Exception as ex:
            errors.append(f"{path}: {ex}")

    logger.info("从 %s 解析到 %d 篇文档", root, len(documents))
    return documents, errors
