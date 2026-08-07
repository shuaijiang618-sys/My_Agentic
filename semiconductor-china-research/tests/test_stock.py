"""Block 3C · 行情快照单元测试(不调用 akshare 网络)。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend import stock  # noqa: E402


class TestStockSnapshot(unittest.TestCase):
    def test_normalize_code6(self):
        self.assertEqual(stock.normalize_code6("002371.SZ"), "002371")
        self.assertEqual(stock.normalize_code6("688981"), "688981")

    def test_resolve_symbols_from_task(self):
        codes = stock.resolve_symbols("北方华创估值 002371")
        self.assertIn("002371", codes)

    @patch("backend.stock.akshare_available", return_value=True)
    @patch("backend.stock.fetch_snapshots")
    def test_stock_snapshot_format(self, mock_fetch, _mock_ak):
        mock_fetch.return_value = [{
            "code": "002371",
            "name": "北方华创",
            "price": 300.0,
            "pe": 40.5,
            "market_cap": 160000000000,
            "change_pct": 1.2,
            "market": "A",
            "as_of": "2026-07-08 14:00",
            "source": "test",
        }]
        text, snaps = stock.stock_snapshot("002371")
        self.assertEqual(len(snaps), 1)
        self.assertIn("北方华创", text)
        self.assertIn("as_of:2026-07-08 14:00", text)
        self.assertIn("不构成投资建议", text)

    @patch("backend.server.akshare_available", return_value=True)
    @patch("backend.server.stock_snapshot")
    def test_stock_snapshot_api(self, mock_ss, _mock_ak):
        mock_ss.return_value = (
            "【行情快照】\n- 北方华创 (002371) · as_of:2026-07-08",
            [{"code": "002371", "name": "北方华创", "price": 1, "pe": 2,
              "market_cap": 3, "as_of": "2026-07-08", "market": "A"}],
        )
        client = TestClient(app)
        r = client.get("/api/stock-snapshot", params={"symbols": "002371"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["provider"], "akshare")

    def test_health_stock_fields(self):
        client = TestClient(app)
        d = client.get("/api/health").json()
        self.assertIn("stock_snapshot", d)
        self.assertIn("stock_snapshot", d["sse_events"])


if __name__ == "__main__":
    unittest.main()
