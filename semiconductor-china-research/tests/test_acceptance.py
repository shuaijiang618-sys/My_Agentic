"""Block 9 · 离线验收测试（不调用 DeepSeek API）。"""
import json
import os
import sqlite3
import tempfile
import unittest

# 必须在 import backend 前注入，避免 config 抛 RuntimeError
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.agent import WORKERS, TOOL_DESC  # noqa: E402
from backend.server import _friendly_api_error  # noqa: E402
from backend.quality import apply_compliance  # noqa: E402
from backend import store  # noqa: E402
from backend.tool import list_search_strategies  # noqa: E402


class TestHealthAndAgents(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_deepseek_metadata(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["provider"], "deepseek")
        self.assertEqual(d["model"], "deepseek-v4-pro")
        self.assertEqual(d["experts"], 8)
        self.assertIn("tool_call", d["sse_events"])
        self.assertIn("kb_hit", d["sse_events"])
        self.assertIn("stock_snapshot", d["sse_events"])
        self.assertIn("fact_check", d["sse_events"])
        self.assertIn("compliance", d["sse_events"])
        self.assertIn("error", d["sse_events"])
        self.assertTrue(d.get("fact_check"))
        self.assertTrue(d.get("compliance_filter"))
        self.assertTrue(d.get("pdf_export"))
        self.assertIn("compliance_rescan", d["sse_events"])

    def test_agents_eight_workers(self):
        r = self.client.get("/api/agents")
        self.assertEqual(r.status_code, 200)
        workers = r.json()["workers"]
        self.assertEqual(len(workers), 8)
        tools = {w["tool"] for w in workers}
        self.assertIn("investment_expert", tools)
        self.assertIn("policy_expert", tools)

    def test_search_strategies_count(self):
        r = self.client.get("/api/search-strategies")
        self.assertEqual(r.status_code, 200)
        strategies = r.json()["strategies"]
        self.assertEqual(len(strategies), 8)
        names = {s["expert"] for s in strategies}
        self.assertEqual(names, set(TOOL_DESC.keys()))


class TestSSEEdgeCases(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_empty_query_returns_error_event(self):
        with self.client.stream("GET", "/api/run", params={"query": ""}) as resp:
            self.assertEqual(resp.status_code, 200)
            body = "".join(resp.iter_text())
        self.assertIn("event: error", body)
        self.assertIn("query 不能为空", body)


class TestInvestmentCompliance(unittest.TestCase):
    def test_disclaimer_appended_for_valuation_query(self):
        brief = "## 结论\n北方华创 PE 约 40 倍。"
        out, meta = apply_compliance(brief, "北方华创估值贵不贵")
        self.assertIn("不构成投资建议", out)
        self.assertTrue(meta["disclaimer_appended"])

    def test_disclaimer_not_duplicated(self):
        brief = "分析完毕。\n\n> 以上内容不构成投资建议。"
        out, _ = apply_compliance(brief, "估值")
        self.assertEqual(out.count("不构成投资建议"), 1)

    def test_friendly_api_error_401(self):
        msg = _friendly_api_error(Exception("401 authentication failed"))
        self.assertIn("DEEPSEEK_API_KEY", msg)

    def test_friendly_api_error_429(self):
        msg = _friendly_api_error(Exception("429 rate limit exceeded"))
        self.assertIn("限流", msg)


class TestStoreMemory(unittest.TestCase):
    def test_brief_summary_truncation(self):
        long_text = "x" * 500
        s = store.brief_summary(long_text, limit=400)
        self.assertLessEqual(len(s), 401)
        self.assertTrue(s.endswith("…"))

    def test_load_history_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test_runs.db")
            orig = store.RUNS_DB
            store.RUNS_DB = db_path
            try:
                c = sqlite3.connect(db_path)
                c.execute(
                    "CREATE TABLE runs(id TEXT, ts REAL, session TEXT, query TEXT, events TEXT, brief TEXT, "
                    "request_id TEXT, duration_ms INTEGER)"
                )
                for i in range(7):
                    c.execute(
                        "INSERT INTO runs(id, ts, session, query, events, brief) VALUES(?,?,?,?,?,?)",
                        (f"id{i}", float(i), "mem-test", f"q{i}", "[]", f"b{i}"),
                    )
                c.commit()
                c.close()
                hist = store.load_history("mem-test", limit=5)
                self.assertEqual(len(hist), 5)
                self.assertEqual(hist[0][0], "q2")
                self.assertEqual(hist[-1][0], "q6")
            finally:
                store.RUNS_DB = orig


class TestWorkerDefinitions(unittest.TestCase):
    def test_eight_experts_with_investment(self):
        self.assertEqual(len(WORKERS), 8)
        tools = [w["tool"] for w in WORKERS]
        self.assertEqual(len(tools), len(set(tools)))
        self.assertIn("investment_expert", tools)
        for w in WORKERS:
            self.assertIn(w["tool"], TOOL_DESC)

    def test_list_search_strategies_matches_workers(self):
        strategies = list_search_strategies()
        self.assertEqual(len(strategies), len(WORKERS))


if __name__ == "__main__":
    unittest.main()
