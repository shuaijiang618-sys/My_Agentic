"""Block 3B · 知识库单元测试。"""
import os
import tempfile
import unittest

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend import kb  # noqa: E402
from backend.seed.industry_kb import seed, LISTED  # noqa: E402


class TestKnowledgeBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._orig_db = kb.INDUSTRY_KB_DB
        kb.INDUSTRY_KB_DB = os.path.join(cls._tmpdir.name, "test_kb.db")
        import sqlite3
        seed(sqlite3.connect(kb.INDUSTRY_KB_DB))

    @classmethod
    def tearDownClass(cls):
        kb.INDUSTRY_KB_DB = cls._orig_db
        cls._tmpdir.cleanup()

    def test_seed_thirty_listed(self):
        self.assertEqual(len(LISTED), 30)
        stats = kb.kb_stats()
        self.assertEqual(stats["listed_semiconductor"], 30)

    def test_lookup_by_symbol(self):
        rows = kb.lookup_by_symbol("002371")
        self.assertTrue(any(r["name"] == "北方华创" for r in rows))

    def test_investment_lookup_fund(self):
        text = kb.kb_investment_lookup("大基金三期投向")
        self.assertIn("大基金", text)
        self.assertIn("3440", text)

    def test_investment_lookup_company(self):
        text = kb.kb_investment_lookup("北方华创估值")
        self.assertIn("北方华创", text)
        self.assertIn("002371", text)

    def test_knowledge_api_segment(self):
        client = TestClient(app)
        r = client.get("/api/knowledge", params={"segment": "equipment"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["enabled"])
        names = {x["name"] for x in d["listed"]}
        self.assertIn("北方华创", names)

    def test_health_kb_stats(self):
        client = TestClient(app)
        d = client.get("/api/health").json()
        self.assertTrue(d.get("knowledge_base"))
        self.assertEqual(d["kb_stats"]["listed_semiconductor"], 30)


if __name__ == "__main__":
    unittest.main()
