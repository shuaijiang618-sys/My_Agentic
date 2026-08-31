#!/usr/bin/env python3
"""扫描 MIN_RETRIEVAL_SCORE 候选阈值（0.30–0.55），输出推荐值与指标表。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def _build_kb():
    from mcp.knowledge_base import KnowledgeBase

    return KnowledgeBase(
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        chroma_path=os.getenv(
            "CHROMA_PERSIST_DIRECTORY",
            str(ROOT / "data/chroma"),
        ),
    )


def _direct_search_fn(kb, top_k: int):
    def search(query: str):
        return kb.search(query, top_k=top_k)
    return search


def _build_rewrite_search_fn(top_k: int):
    from mcp.tool_manager import MCPToolManager, Tool

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if deepseek_key:
        api_key = deepseek_key
        from core.llm_utils import normalize_anthropic_base_url

        raw = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or None
        base_url = normalize_anthropic_base_url(raw) if raw else None
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    elif anthropic_key:
        api_key = anthropic_key
        from core.llm_utils import normalize_anthropic_base_url

        raw = os.getenv("ANTHROPIC_BASE_URL", "").strip() or None
        base_url = normalize_anthropic_base_url(raw) if raw else None
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()
    else:
        raise RuntimeError("rewrite 模式需要 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY")

    from mcp.tool_manager import MCPToolManager, Tool

    kb = _build_kb()
    tm = MCPToolManager(api_key=api_key, base_url=base_url, model=model)

    async def handler(params, context):
        return await kb.search_handler(params, context)

    tm.register(Tool(
        name="knowledge_search",
        description="eval",
        handler=handler,
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
            "required": ["query"],
        },
        cache_ttl=0.0,
        supports_rerank=True,
    ))

    async def async_search(query: str):
        result = await tm.search_with_rewrite("knowledge_search", query, top_k=top_k)
        return result.data if result.success and isinstance(result.data, list) else []

    def search(query: str):
        return asyncio.run(async_search(query))

    return search


def _print_table(report: dict) -> None:
    print("\n=== Top-1 分数分布 ===")
    dist = report["distribution"]
    for label in ("should_answer", "should_reject"):
        s = dist[label]
        print(
            f"  {label}: n={s['count']} with_score={s.get('with_score', 0)} "
            f"median={s.get('median', '-')} p10={s.get('p10', '-')} p90={s.get('p90', '-')}"
        )

    print("\n=== 逐条检索 ===")
    for q in report["queries"]:
        flag = "应答" if q["should_answer"] else "应拒"
        score = q["top_score"]
        score_s = f"{score:.4f}" if score is not None else "None"
        title = (q["top_title"] or "-")[:24]
        print(f"  [{flag}] {q['name']:18} score={score_s:>8}  title={title}")

    print("\n=== 阈值扫描 (误放行优先) ===")
    print(f"{'阈值':>6}  {'误拒答率':>10}  {'误放行率':>10}  {'召回':>8}  {'精确':>8}")
    for row in report["threshold_sweep"]:
        mark = " ← 当前" if abs(row["threshold"] - report["current_threshold"]) < 1e-6 else ""
        rec = report["recommendation"]["threshold"]
        if abs(row["threshold"] - rec) < 1e-6:
            mark = " ← 推荐"
        print(
            f"{row['threshold']:6.2f}  "
            f"{row['false_reject_rate']:10.1%}  "
            f"{row['false_accept_rate']:10.1%}  "
            f"{row['recall_pass']:8.1%}  "
            f"{row['precision_pass']:8.1%}{mark}"
        )

    rec = report["recommendation"]
    cur = report["current_metrics"]
    print(
        f"\n当前阈值 {report['current_threshold']} → "
        f"误拒答 {cur.get('false_reject_rate')} / 误放行 {cur.get('false_accept_rate')}"
    )
    print(f"推荐阈值 {rec['threshold']} → {rec['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG MIN_RETRIEVAL_SCORE 阈值标定")
    parser.add_argument(
        "--mode",
        choices=("direct", "rewrite"),
        default="direct",
        help="direct=仅向量检索；rewrite=与线上一致的改写+重排（需 API Key）",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--start", type=float, default=0.30)
    parser.add_argument("--end", type=float, default=0.55)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument(
        "--max-false-accept",
        type=float,
        default=0.0,
        help="推荐阈值时允许的最大误放行率（默认 0）",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=None,
        help="自定义评测 JSON，默认 evaluation/retrieval_cases.json",
    )
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    from core.medical_security import MIN_RETRIEVAL_SCORE
    from evaluation.retrieval_cases import load_retrieval_cases
    from evaluation.retrieval_threshold_runner import run_retrieval_threshold_eval

    if args.mode == "direct":
        kb = _build_kb()
        search_fn = _direct_search_fn(kb, args.top_k)
        mode_note = f"direct (kb_chunks={kb.doc_count})"
    else:
        search_fn = _build_rewrite_search_fn(args.top_k)
        mode_note = "rewrite (search_with_rewrite)"

    cases = load_retrieval_cases(args.cases)
    report = run_retrieval_threshold_eval(
        search_fn,
        cases=cases,
        current_threshold=MIN_RETRIEVAL_SCORE,
        start=args.start,
        end=args.end,
        step=args.step,
        max_false_accept_rate=args.max_false_accept,
    )
    report["mode"] = mode_note

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"模式: {mode_note}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        _print_table(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
