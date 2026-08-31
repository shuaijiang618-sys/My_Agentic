# -*- coding: utf-8 -*-
"""LLM 偏题分类（扩展 regex 门禁）。"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from core.llm_utils import create_message, extract_text_content

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """你是医疗导诊系统的主题分类器。

本系统**只做**：症状导诊、检查/报告指标解释、挂号与就诊流程说明。
**不做**：写代码、理财、娱乐闲聊、政治、法律等非医疗主题。

用户消息: "{message}"

返回 JSON: {{"off_topic": true/false, "reason": "<一句话>"}}
off_topic=true 表示超出业务范围。"""


def off_topic_llm_enabled() -> bool:
    return os.getenv("OFF_TOPIC_LLM_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def off_topic_llm_always() -> bool:
    return os.getenv("OFF_TOPIC_LLM_ALWAYS", "false").strip().lower() in ("1", "true", "yes")


def should_run_off_topic_llm(message: str) -> bool:
    """无明确医疗关键词且非纯寒暄时，才调用 LLM（控成本）。"""
    if not off_topic_llm_enabled():
        return False
    if off_topic_llm_always():
        return True
    from core.medical_security import has_medical_hint, is_greeting_only

    msg = (message or "").strip()
    if not msg or is_greeting_only(msg):
        return False
    if has_medical_hint(msg):
        return False
    return True


async def llm_classify_off_topic(client: Any, model: str, message: str) -> tuple[bool, str]:
    """
    返回 (is_off_topic, reason)。
    解析/调用失败时 fail-open（视为 in-scope）。
    """
    prompt = _CLASSIFY_PROMPT.format(message=(message or "")[:500])
    try:
        resp = await create_message(
            client,
            stage="off_topic_classify",
            model=model,
            max_tokens=128,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = extract_text_content(resp.content)
        s, e = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[s:e])
        off = bool(data.get("off_topic", False))
        reason = str(data.get("reason", ""))
        return off, reason
    except Exception as ex:
        logger.warning("偏题 LLM 分类失败（fail-open 放行）: %s", ex)
        return False, ""
