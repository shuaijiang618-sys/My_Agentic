# -*- coding: utf-8 -*-
"""医疗安全门禁：紧急症状、越权诊疗、主题边界、PII 脱敏。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

_OFF_TOPIC_PATTERNS = (
    r"写.{0,4}代码|python|javascript|股票|比特币|天气怎么样",
    r"讲个笑话|聊天吧|游戏攻略",
)

_HIGH_RISK_INPUT_PATTERNS = (
    r"确诊|是不是得了|我得了什么病|帮我诊断",
    r"开方|处方|方剂|开药",
    r"剂量|用量|吃多少|几克|几片|一天几次",
    r"吃什么药|用什么药|推荐.{0,4}药|该买哪种药",
    r"帮我治|给我治|怎么治我",
)

_EMERGENCY_PATTERNS = (
    r"胸痛|胸口.{0,2}痛|心口.{0,2}痛|压榨性疼痛",
    r"呼吸困难|喘不上气|窒息|呼吸急促",
    r"意识不清|昏迷|晕厥|叫不应|抽搐不止",
    r"大量出血|吐血|便血.{0,4}喷|止不住的血",
    r"自杀|不想活|自残",
    r"剧烈头痛.{0,6}呕吐|突发.{0,4}偏瘫|口角歪斜|说话不清",
)

_MEDICAL_HINTS = (
    "症状", "挂号", "科室", "检查", "报告", "指标", "体检", "化验",
    "血压", "血糖", "ALT", "AST", "mmol", "偏高", "偏低", "异常",
    "导诊", "门诊", "急诊", "就医", "医院",
)

# 模块级模板（启动时从 prompts/security/*.md 同步，保留常量名供现有 import）
DISCLAIMER = (
    "**免责声明**：本回答仅供参考，不能替代医生诊断与处方，"
    "请以线下医疗机构的专业意见为准。如有不适，请及时就医。"
)
EMERGENCY_RESPONSE = ""
BLOCK_OFF_TOPIC = ""
BLOCK_HIGH_RISK = ""
BLOCK_NO_EVIDENCE = ""
BLOCK_SENSITIVE = ""
BLOCK_EMPTY_AGENT = ""

MIN_RETRIEVAL_SCORE = 0.4

ERROR_CODE_MAP = {
    "empty": "INVALID_REQUEST",
    "too_long": "QUESTION_TOO_LONG",
    "off_topic": "TOPIC_OUT_OF_SCOPE",
    "high_risk_medical": "TOPIC_OUT_OF_SCOPE",
    "emergency": "EMERGENCY",
    "low_retrieval_high_risk": "TOPIC_OUT_OF_SCOPE",
    "no_retrieval": "NO_EVIDENCE",
    "low_retrieval": "NO_EVIDENCE",
    "sensitive_content": "TOPIC_OUT_OF_SCOPE",
    "empty_agent_response": "EMPTY_RESPONSE",
    "off_topic_llm": "TOPIC_OUT_OF_SCOPE",
}


def sync_templates_from_registry(registry) -> None:
    """由 PromptRegistry 初始化/热加载时调用。"""
    global DISCLAIMER, EMERGENCY_RESPONSE, BLOCK_OFF_TOPIC
    global BLOCK_HIGH_RISK, BLOCK_NO_EVIDENCE
    global BLOCK_SENSITIVE, BLOCK_EMPTY_AGENT
    DISCLAIMER = registry.disclaimer
    EMERGENCY_RESPONSE = registry.emergency_response
    BLOCK_OFF_TOPIC = registry.block_off_topic
    BLOCK_HIGH_RISK = registry.block_high_risk
    BLOCK_NO_EVIDENCE = registry.block_no_evidence
    BLOCK_SENSITIVE = registry.block_sensitive
    BLOCK_EMPTY_AGENT = registry.block_empty_agent


def _ensure_templates() -> None:
    if EMERGENCY_RESPONSE:
        return
    from core.prompt_registry import get_registry
    sync_templates_from_registry(get_registry())


@dataclass
class SecurityCheckResult:
    allowed: bool
    blocked_reason: Optional[str]
    hitl_required: bool
    response_text: Optional[str]
    emergency: bool = False

    @property
    def error_code(self) -> str:
        return ERROR_CODE_MAP.get(self.blocked_reason or "", "INVALID_REQUEST")


def redact_pii(text: str) -> str:
    text = re.sub(r"(?<=\d{3})\d{4}(?=\d{4})", "****", text)
    text = re.sub(
        r"\b1[3-9]\d{9}\b",
        lambda m: m.group()[:3] + "****" + m.group()[-4:],
        text,
    )
    return text


def _matches_any(text: str, patterns: Tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def detect_emergency(question: str) -> bool:
    return _matches_any((question or "").strip(), _EMERGENCY_PATTERNS)


def has_medical_hint(question: str) -> bool:
    q = (question or "").lower()
    return any(h.lower() in q for h in _MEDICAL_HINTS)


def is_greeting_only(question: str) -> bool:
    msg = (question or "").strip().lower()
    return msg in {"你好", "您好", "hi", "hello", "嗨"}


def min_agent_response_chars() -> int:
    import os

    return max(1, int(os.getenv("MIN_AGENT_RESPONSE_CHARS", "8")))


def check_empty_agent_response(text: str) -> Optional[SecurityCheckResult]:
    """Agent 正文过短/为空 → 强制拒答。"""
    _ensure_templates()
    if len((text or "").strip()) >= min_agent_response_chars():
        return None
    return SecurityCheckResult(
        False,
        "empty_agent_response",
        True,
        BLOCK_EMPTY_AGENT,
    )


def check_question(question: str) -> SecurityCheckResult:
    _ensure_templates()
    from core.prompt_registry import get_registry
    reg = get_registry()

    q = (question or "").strip()
    if not q:
        return SecurityCheckResult(False, "empty", False, reg.security("empty"))
    if len(q) > 2000:
        return SecurityCheckResult(False, "too_long", False, reg.security("too_long"))

    if detect_emergency(q):
        return SecurityCheckResult(
            False, "emergency", True, EMERGENCY_RESPONSE, emergency=True,
        )

    if _matches_any(q, _HIGH_RISK_INPUT_PATTERNS):
        return SecurityCheckResult(False, "high_risk_medical", True, BLOCK_HIGH_RISK)

    if _matches_any(q, _OFF_TOPIC_PATTERNS):
        return SecurityCheckResult(False, "off_topic", False, BLOCK_OFF_TOPIC)

    from core.content_safety import check_sensitive_input

    if hit := check_sensitive_input(q):
        logger.info("输入敏感词拦截: pattern=%s", hit)
        return SecurityCheckResult(False, "sensitive_content", True, BLOCK_SENSITIVE)

    if is_greeting_only(q):
        return SecurityCheckResult(True, None, False, None)

    if len(q) < 6 and not has_medical_hint(q):
        return SecurityCheckResult(False, "off_topic", False, BLOCK_OFF_TOPIC)

    return SecurityCheckResult(True, None, False, None)


async def check_question_async(
    question: str,
    *,
    llm_client: Any = None,
    llm_model: str = "",
) -> SecurityCheckResult:
    """输入预检 + 可选偏题 LLM / 内容安全 API。"""
    sec = check_question(question)
    if not sec.allowed:
        return sec

    from core.content_safety import check_content_safety_api, content_safety_api_enabled
    from core.off_topic_classifier import llm_classify_off_topic, should_run_off_topic_llm

    if content_safety_api_enabled():
        api_unsafe = await check_content_safety_api(question, direction="input")
        if api_unsafe is True:
            _ensure_templates()
            return SecurityCheckResult(False, "sensitive_content", True, BLOCK_SENSITIVE)

    if llm_client and should_run_off_topic_llm(question):
        off, reason = await llm_classify_off_topic(llm_client, llm_model, question)
        if off:
            logger.info("偏题 LLM 拦截: %s", reason or "off_topic")
            _ensure_templates()
            return SecurityCheckResult(
                False,
                "off_topic_llm",
                False,
                BLOCK_OFF_TOPIC,
            )

    return sec


def check_retrieval_score(top_score: Optional[float], question: str) -> SecurityCheckResult:
    _ensure_templates()
    if top_score is not None and top_score >= MIN_RETRIEVAL_SCORE:
        return SecurityCheckResult(True, None, False, None)
    if _matches_any(question, _HIGH_RISK_INPUT_PATTERNS):
        return SecurityCheckResult(False, "low_retrieval_high_risk", True, BLOCK_HIGH_RISK)
    return SecurityCheckResult(False, "low_retrieval", True, BLOCK_NO_EVIDENCE)


def check_knowledge_gate(
    question: str,
    *,
    evidence_required: bool,
    source_count: int,
    top_score: Optional[float],
) -> SecurityCheckResult:
    if not evidence_required:
        return SecurityCheckResult(True, None, False, None)
    if source_count <= 0 or top_score is None:
        return SecurityCheckResult(False, "no_retrieval", True, BLOCK_NO_EVIDENCE)
    return check_retrieval_score(top_score, question)


def append_disclaimer(text: str) -> str:
    _ensure_templates()
    body = (text or "").strip()
    if DISCLAIMER.replace("*", "")[:20] in body.replace("*", ""):
        return body
    return f"{body}\n\n{DISCLAIMER}" if body else DISCLAIMER
