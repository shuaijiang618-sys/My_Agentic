"""Phase 3 M3.2 · 导出 API 单元测试。"""
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.export import export_session_markdown, export_session_pdf  # noqa: E402
from backend import store  # noqa: E402


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_db = store.RUNS_DB
        store.RUNS_DB = os.path.join(self.tmp.name, "runs.db")
        self.client = TestClient(app)
        c = sqlite3.connect(store.RUNS_DB)
        c.execute(
            "CREATE TABLE runs(id TEXT PRIMARY KEY, ts REAL, session TEXT, query TEXT, "
            "events TEXT, brief TEXT, request_id TEXT, duration_ms INTEGER)"
        )
        c.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
            ("r1", 1.0, "exp-sess", "北方华创估值", "[]", "## 结论\nPE 约 40 倍。", "req1", 1200),
        )
        c.commit()
        c.close()

    def tearDown(self):
        store.RUNS_DB = self.orig_db
        self.tmp.cleanup()

    def test_markdown_export(self):
        md, meta = export_session_markdown("exp-sess")
        self.assertIsNotNone(md)
        self.assertIn("北方华创估值", md)
        self.assertEqual(meta["format"], "md")

    def test_pdf_export_bytes(self):
        pdf, meta = export_session_pdf("exp-sess")
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(meta["format"], "pdf")

    def test_export_api_md(self):
        r = self.client.get("/api/export", params={"session": "exp-sess", "format": "md"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("北方华创", r.text)

    def test_export_api_pdf(self):
        r = self.client.get("/api/export", params={"session": "exp-sess", "format": "pdf"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_export_missing_session(self):
        r = self.client.get("/api/export", params={"session": "no-such"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("error", r.json())


if __name__ == "__main__":
    unittest.main()
