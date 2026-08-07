"""Phase 3 M3.3 · 观测与统计单元测试。"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend import observability  # noqa: E402
from backend import store  # noqa: E402


class TestObservability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_log = observability.RUNS_LOG
        observability.RUNS_LOG = observability.LOGS / f"test-{os.getpid()}.jsonl"
        if observability.RUNS_LOG.exists():
            observability.RUNS_LOG.unlink()
        self.client = TestClient(app)

    def tearDown(self):
        if observability.RUNS_LOG.exists():
            observability.RUNS_LOG.unlink()
        observability.RUNS_LOG = self.orig_log
        self.tmp.cleanup()

    def test_new_request_id_length(self):
        rid = observability.new_request_id()
        self.assertEqual(len(rid), 12)

    def test_log_and_recent(self):
        observability.log_run(
            request_id="abc123",
            session="s1",
            query="测试",
            duration_ms=1000,
            run_id="r1",
        )
        runs = observability.recent_runs(limit=5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["request_id"], "abc123")

    def test_stats_api(self):
        r = self.client.get("/api/stats")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("db", d)
        self.assertIn("observability", d)
        self.assertIn("recent", d)

    def test_db_stats(self):
        stats = store.db_stats()
        self.assertIn("total_runs", stats)


if __name__ == "__main__":
    unittest.main()
