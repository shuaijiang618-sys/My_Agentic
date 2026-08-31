# -*- coding: utf-8 -*-
"""结构化 Agent 输出：JSON 解析 + Markdown 模板渲染 + 字段校验。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SECTION_HEADERS = {
    "triage": ("## 症状理解", "## 建议咨询科室", "## 就医建议"),
    "report": ("## 指标含义", "## 常见影响因素", "## 建议下一步"),
    "general": ("## 问题理解", "## 解答"),
}


def build_retry_user_message(required_fields: List[str]) -> str:
    """结构化解析失败时，追加到多轮 messages 的纠正提示。"""
    fields = "、".join(required_fields) if required_fields else "全部必填字段"
    return (
        "【纠正】上一条回复无法解析为有效 JSON，或缺少必填字段。"
        f"请严格只返回一个 JSON 对象，必填字段：{fields}。"
        "不要 Markdown 代码块，不要任何前后说明。"
    )


def extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """从 LLM 文本中提取第一个 JSON 对象。"""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _missing_fields(data: Dict[str, Any], required: List[str]) -> List[str]:
    missing: List[str] = []
    for key in required:
        val = data.get(key)
        if val is None:
            missing.append(key)
            continue
        if isinstance(val, str) and not val.strip():
            missing.append(key)
        if isinstance(val, list) and key == "suggested_departments" and not val:
            missing.append(key)
    return missing


def _format_departments(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return (
            "建议携带症状描述前往医院**分诊台**或**全科/内科**进一步评估；"
            "具体科室以现场分诊为准。"
        )
    lines: List[str] = []
    for i, item in enumerate(items[:2], start=1):
        if isinstance(item, str):
            lines.append(f"{i}. **{item.strip()}**")
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("department") or "相关科室").strip()
        reason = str(item.get("reason") or "").strip()
        if reason:
            lines.append(f"{i}. **{name}**：{reason}")
        else:
            lines.append(f"{i}. **{name}**")
    return "\n".join(lines) if lines else "请以现场分诊为准选择科室。"


def _format_bullet_list(items: Any, *, empty: str) -> str:
    if not isinstance(items, list) or not items:
        return empty
    lines = [f"- {str(x).strip()}" for x in items[:4] if str(x).strip()]
    return "\n".join(lines) if lines else empty


def _format_clarifying(questions: Any) -> str:
    if not isinstance(questions, list) or not questions:
        return ""
    lines = [f"- {str(q).strip()}" for q in questions[:3] if str(q).strip()]
    if not lines:
        return ""
    return "\n\n## 建议补充信息\n" + "\n".join(lines)


def _format_follow_up(note: Any, *, heading: str = "## 补充说明") -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    return f"\n\n{heading}\n{text}"


def _format_blockquote(note: Any) -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    return f"\n\n> {text}"


def render_from_template(template_text: str, variables: Dict[str, str]) -> str:
    return template_text.format(**variables).strip()


def render_structured(agent_key: str, data: Dict[str, Any], template_text: str) -> str:
    if agent_key == "triage":
        variables = {
            "symptom_summary": str(data.get("symptom_summary", "")).strip(),
            "departments_block": _format_departments(data.get("suggested_departments")),
            "visit_advice": str(data.get("visit_advice", "")).strip(),
            "clarifying_block": _format_clarifying(data.get("clarifying_questions")),
        }
    elif agent_key == "report":
        variables = {
            "indicator_meaning": str(data.get("indicator_meaning", "")).strip(),
            "common_factors_block": _format_bullet_list(
                data.get("common_factors"),
                empty="个体差异较大，常见与作息、饮食、近期感染或检测条件有关，需结合临床判断。",
            ),
            "next_steps": str(data.get("next_steps", "")).strip(),
            "data_note_block": _format_blockquote(data.get("data_note")),
        }
    elif agent_key == "general":
        variables = {
            "topic_summary": str(data.get("topic_summary", "")).strip(),
            "answer": str(data.get("answer", "")).strip(),
            "tips_block": _format_bullet_list(
                data.get("practical_tips"),
                empty="",
            ),
            "follow_up_block": _format_follow_up(data.get("follow_up")),
        }
        if variables["tips_block"]:
            variables["tips_block"] = "\n\n**实用提示**\n" + variables["tips_block"]
    else:
        return str(data.get("text") or data.get("content") or "").strip()

    return render_from_template(template_text, variables)


def validate_rendered_sections(agent_key: str, text: str) -> List[str]:
    headers = _SECTION_HEADERS.get(agent_key, ())
    missing = [h for h in headers if h not in (text or "")]
    return missing


def build_agent_response(
    agent_key: str,
    raw_llm_text: str,
    *,
    template_text: str,
    required_fields: List[str],
    fallback_to_raw: bool = True,
) -> Tuple[str, bool]:
    """
    解析 JSON → 校验字段 → 模板渲染。
    返回 (用户可见文本, structured_ok)。
    """
    data = extract_json_object(raw_llm_text)
    if data is None:
        logger.warning("结构化输出解析失败 agent=%s，回退原文", agent_key)
        body = (raw_llm_text or "").strip()
        return (body, False) if fallback_to_raw and body else ("抱歉，暂时无法生成结构化回复，请稍后重试或前往医疗机构咨询。", False)

    missing = _missing_fields(data, required_fields)
    if missing:
        logger.warning("结构化输出缺字段 agent=%s missing=%s", agent_key, missing)

    rendered = render_structured(agent_key, data, template_text)
    section_missing = validate_rendered_sections(agent_key, rendered)
    if section_missing:
        logger.warning("渲染后缺段落 agent=%s sections=%s", agent_key, section_missing)

    ok = not missing and not section_missing
    if ok:
        return rendered, True

    if fallback_to_raw and (raw_llm_text or "").strip():
        return (raw_llm_text or "").strip(), False
    return rendered, False
