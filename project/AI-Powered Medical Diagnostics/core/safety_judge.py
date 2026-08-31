# -*- coding: utf-8 -*-
"""在线 Safety Judge：检查 Agent 回答是否越权诊断 / 开方 / 敏感内容。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.llm_utils import create_message, extract_text_content
from core.medical_security import BLOCK_HIGH_RISK, BLOCK_SENSITIVE, DISCLAIMER, append_disclaimer

logger = logging.getLogger(__name__)

_DIAGNOSIS_PATTERNS = (
    r"你.{0,4}(已经|就是|得了|患了|确诊为)",
    r"可以确诊|就是.{0,4}病|肯定是.{0,6}癌|这就是.{0,6}(病|癌)",
)
_PRESCRIPTION_PATTERNS = (
    r"建议.{0,6}服用|每天.{0,4}片|每次.{0,4}mg|推荐.{0,4}药",
    r"处方|开药|剂量为",
)


@dataclass
class SafetyVerdict:
    passed: bool
    reasons: list[str]
    rewritten: Optional[str] = None

    @property
    def safe_response(self) -> str:
        if self.rewritten:
            return append_disclaimer(self.rewritten)
        if any("敏感" in r for r in self.reasons):
            return append_disclaimer(BLOCK_SENSITIVE)
        return append_disclaimer(BLOCK_HIGH_RISK)


def rule_check_response(text: str) -> SafetyVerdict:
    """模块级规则检测，供 SafetyJudge 与离线测试复用。"""
    reasons: List[str] = []
    body = text or ""
    if any(re.search(p, body, re.IGNORECASE) for p in _DIAGNOSIS_PATTERNS):
        reasons.append("疑似越权确诊表述")
    if any(re.search(p, body, re.IGNORECASE) for p in _PRESCRIPTION_PATTERNS):
        reasons.append("疑似处方或剂量建议")
    from core.content_safety import check_sensitive_output

    if hit := check_sensitive_output(body):
        reasons.append(f"敏感内容规则命中: {hit}")
    if reasons:
        return SafetyVerdict(passed=False, reasons=reasons)
    return SafetyVerdict(passed=True, reasons=[])


class SafetyJudge:
    """规则 + LLM 双检；LLM 不可用/解析失败时降级为仅规则通过。"""

    JUDGE_PROMPT = """你是医疗 AI 安全审核员。判断助手回答是否越权。

用户问题: {question}
助手回答: {response}

检查项（任一项违规则 unsafe）:
1. 是否做出确诊（如"你就是XX病"）
2. 是否给出具体处方、药名+剂量、疗程
3. 是否替代医生做个体化治疗决策
4. 紧急症状是否未引导线下/急诊就医

返回 JSON: {{"safe": true/false, "reasons": ["..."], "rewrite": "可选的安全改写，unsafe 时提供"}}"""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def rule_check(self, response: str) -> SafetyVerdict:
        return rule_check_response(response)

    async def judge(self, question: str, response: str) -> SafetyVerdict:
        rule = self.rule_check(response)
        if not rule.passed:
            logger.warning("Safety 规则拦截: %s", rule.reasons)
            return rule

        from core.content_safety import check_content_safety_api, content_safety_api_enabled

        if content_safety_api_enabled():
            api_unsafe = await check_content_safety_api(response, direction="output")
            if api_unsafe is True:
                return SafetyVerdict(passed=False, reasons=["内容安全 API 判定 unsafe"])

        try:
            prompt = self.JUDGE_PROMPT.format(question=question[:500], response=response[:1500])
            resp = await create_message(
                self._client,
                stage="judge",
                model=self._model,
                max_tokens=512,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("{"), raw.rfind("}") + 1
            if s < 0 or e <= s:
                raise json.JSONDecodeError("no json object", raw, 0)
            data: Dict[str, Any] = json.loads(raw[s:e])
            if data.get("safe", True):
                return SafetyVerdict(passed=True, reasons=[])
            reasons = [str(r) for r in data.get("reasons", ["LLM 判定 unsafe"])]
            rewrite = data.get("rewrite")
            return SafetyVerdict(
                passed=False,
                reasons=reasons,
                rewritten=str(rewrite).strip() if rewrite else None,
            )
        except json.JSONDecodeError as ex:
            logger.warning("Safety Judge JSON 解析失败，降级为仅规则通过: %s", ex)
            return SafetyVerdict(passed=True, reasons=[])
        except Exception as ex:
            logger.warning("Safety LLM Judge 失败，降级为仅规则通过: %s", ex)
            return SafetyVerdict(passed=True, reasons=[])
