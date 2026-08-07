"""Phase 3 · 事实校验与合规过滤单元测试。"""
import os
import unittest

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")

from backend.quality import (  # noqa: E402
    apply_compliance,
    check_facts,
    postprocess_brief,
)


class TestCompliance(unittest.TestCase):
    def test_disclaimer_for_valuation_query(self):
        brief = "## 结论\n北方华创 PE 约 40 倍。"
        out, meta = apply_compliance(brief, "北方华创估值贵不贵")
        self.assertIn("不构成投资建议", out)
        self.assertTrue(meta["disclaimer_appended"])

    def test_disclaimer_not_duplicated(self):
        brief = "分析完毕。\n\n> 以上内容不构成投资建议。"
        out, _ = apply_compliance(brief, "估值")
        self.assertEqual(out.count("不构成投资建议"), 1)

    def test_forbidden_phrase_replaced(self):
        brief = "综合判断建议买入该标的。"
        out, meta = apply_compliance(brief)
        self.assertIn("【表述已合规处理】", out)
        self.assertIn("建议买入", meta["flags"])

    def test_rescan_catches_promise(self):
        from backend.quality import rescan_compliance

        brief = "该股保证翻倍收益。"
        out, meta = rescan_compliance(brief)
        self.assertIn("收益承诺", meta["hits"])
        self.assertIn("【表述已合规处理】", out)


class TestFactCheck(unittest.TestCase):
    def test_rogue_url_warning(self):
        brief = "详见 https://example.com/fake\n\n## 📎 参考来源\n\n1. [a](https://real.com/a)"
        log = [{"title": "a", "href": "https://real.com/a"}]
        r = check_facts(brief, log, ["some snippet text " * 5])
        self.assertFalse(r["passed"])
        self.assertTrue(any("URL" in w for w in r["warnings"]))

    def test_valuation_without_date(self):
        brief = "北方华创 PE 约 40 倍。"
        r = check_facts(brief, [{"href": "https://x.com"}], ["北方华创 PE 40"])
        self.assertTrue(any("日期" in w or "报告期" in w for w in r["warnings"]))

    def test_postprocess_returns_metadata(self):
        brief, meta = postprocess_brief(
            "建议买入某股，PE 50。",
            "估值分析",
            [],
            ["snippet"],
            [],
        )
        self.assertIn("compliance", meta)
        self.assertIn("compliance_rescan", meta)
        self.assertIn("fact_check", meta)
        self.assertIn("不构成投资建议", brief)


if __name__ == "__main__":
    unittest.main()
