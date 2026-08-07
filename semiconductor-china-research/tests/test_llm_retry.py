"""Phase 3 · LLM 429/503 指数退避单元测试。"""
import asyncio
import os
import unittest

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from backend.llm_retry import is_rate_limit_error, run_with_retry  # noqa: E402


class TestRateLimitDetection(unittest.TestCase):
    def test_detects_429(self):
        self.assertTrue(is_rate_limit_error(Exception("HTTP 429 rate limit")))

    def test_detects_timeout(self):
        self.assertTrue(is_rate_limit_error(Exception("request timed out")))

    def test_ignores_other_errors(self):
        self.assertFalse(is_rate_limit_error(Exception("400 bad request")))


class TestRunWithRetry(unittest.IsolatedAsyncioTestCase):
    async def test_succeeds_first_try(self):
        n = {"v": 0}

        async def ok():
            n["v"] += 1
            return "ok"

        r = await run_with_retry(ok, max_retries=3, base_delay=0.01)
        self.assertEqual(r, "ok")
        self.assertEqual(n["v"], 1)

    async def test_retries_on_429(self):
        n = {"v": 0}

        async def flaky():
            n["v"] += 1
            if n["v"] < 2:
                raise RuntimeError("429 rate limit exceeded")
            return "done"

        r = await run_with_retry(flaky, max_retries=3, base_delay=0.01)
        self.assertEqual(r, "done")
        self.assertEqual(n["v"], 2)

    async def test_raises_non_rate_limit_immediately(self):
        async def bad():
            raise ValueError("invalid json")

        with self.assertRaises(ValueError):
            await run_with_retry(bad, max_retries=3, base_delay=0.01)


if __name__ == "__main__":
    unittest.main()
