# -*- coding: utf-8 -*-
"""安全门禁：主题边界、高风险医疗意图、PII 脱敏（SKILL §6 / boundary-checklist §3）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

_OFF_TOPIC_PATTERNS = (
    r"写.{0,4}代码|python|javascript|股票|比特币|天气怎么样",
    r"你是谁|讲个笑话|聊天吧",
)

_HIGH_RISK_PATTERNS = (
    r"帮我治|给我治|怎么治我",
    r"开方|处方|方剂加减",
    r"剂量|用量|吃多少|几克|几片",
    r"确诊|是不是得了|我得了什么病",
    r"吃什么药|用什么药|推荐药",
)

_TCM_HINTS = (
    "证", "证候", "辨证", "中医", "脉", "舌", "寒", "热", "虚", "实",
    "营卫", "六淫", "脏腑", "经络", "方剂", "临床", "症状", "表现",
)

DISCLAIMER = (
    "**免责声明**：本系统仅供中医证候知识辅助学习，不能替代执业医师的诊断、处方或治疗。"
    "如有不适，请及时就医。"
)

BLOCK_OFF_TOPIC = (
    "您的问题超出本系统「中医证候 / 辨证知识」范围。"
    "请提问与证候定义、临床表现、辨证要点相关的内容。"
)

BLOCK_HIGH_RISK = (
    f"{DISCLAIMER}\n\n"
    "个体化诊断、开方或用药剂量需由**执业医师**面诊后决定，本系统无法提供此类建议。"
    "如需帮助，请咨询医疗机构。"
)

MIN_RETRIEVAL_SCORE = 0.4

ERROR_CODE_MAP = {
    "empty": "INVALID_REQUEST",
    "too_long": "QUESTION_TOO_LONG",
    "off_topic": "TOPIC_OUT_OF_SCOPE",
    "high_risk_medical": "TOPIC_OUT_OF_SCOPE",
    "low_retrieval_high_risk": "TOPIC_OUT_OF_SCOPE",
    "internal_error": "INTERNAL_ERROR",
}


@dataclass
class SecurityCheckResult:
    allowed: bool
    blocked_reason: Optional[str]
    hitl_required: bool
    response_text: Optional[str]

    @property
    def error_code(self) -> str:
        return ERROR_CODE_MAP.get(self.blocked_reason or "", "INVALID_REQUEST")


def redact_pii(text: str) -> str:
    text = re.sub(r"(?<=\d{3})\d{4}(?=\d{4})", "****", text)
    text = re.sub(r"\b1[3-9]\d{9}\b", lambda m: m.group()[:3] + "****" + m.group()[-4:], text)
    return text


def _matches_any(text: str, patterns: Tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def validate_question(question: str) -> SecurityCheckResult:
    """API / RAG 入口：长度与空值校验。"""
    return check_question(question)


def check_question(question: str) -> SecurityCheckResult:
    q = (question or "").strip()
    if not q:
        return SecurityCheckResult(False, "empty", False, "请输入您的问题。")
    if len(q) > 2000:
        return SecurityCheckResult(False, "too_long", False, "问题过长，请控制在 2000 字以内。")
    if _matches_any(q, _HIGH_RISK_PATTERNS):
        return SecurityCheckResult(False, "high_risk_medical", True, BLOCK_HIGH_RISK)
    if _matches_any(q, _OFF_TOPIC_PATTERNS):
        return SecurityCheckResult(False, "off_topic", False, BLOCK_OFF_TOPIC)
    if len(q) < 8 and not any(h in q for h in _TCM_HINTS):
        return SecurityCheckResult(False, "off_topic", False, BLOCK_OFF_TOPIC)
    return SecurityCheckResult(True, None, False, None)


def check_retrieval_score(top_score: Optional[float], question: str) -> SecurityCheckResult:
    if top_score is None or top_score >= MIN_RETRIEVAL_SCORE:
        return SecurityCheckResult(True, None, False, None)
    if _matches_any(question, _HIGH_RISK_PATTERNS):
        return SecurityCheckResult(False, "low_retrieval_high_risk", True, BLOCK_HIGH_RISK)
    return SecurityCheckResult(True, None, False, None)
