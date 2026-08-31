# -*- coding: utf-8 -*-
"""泛化敏感词 + 可选内容安全 API。"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_INPUT_PATTERNS = (
    r"色情|裸体|淫秽|卖淫",
    r"赌博|博彩|六合彩",
    r"制[毒爆]|炸弹制作|枪支交易",
    r"自杀方法|自残教程",
)
_DEFAULT_OUTPUT_PATTERNS = (
    r"色情|裸体|淫秽",
    r"赌博|博彩",
    r"制[毒爆]|炸弹制作",
    r"自杀方法|教你怎么死",
)

_input_patterns: Tuple[str, ...] = _DEFAULT_INPUT_PATTERNS
_output_patterns: Tuple[str, ...] = _DEFAULT_OUTPUT_PATTERNS


def reload_sensitive_patterns(root_dir: Optional[Path] = None) -> None:
    """从 prompts/security/sensitive_words.yaml 热加载。"""
    global _input_patterns, _output_patterns
    if root_dir is None:
        from config import PROMPTS_DIR
        root_dir = PROMPTS_DIR
    path = Path(root_dir) / "security" / "sensitive_words.yaml"
    if not path.is_file():
        _input_patterns = _DEFAULT_INPUT_PATTERNS
        _output_patterns = _DEFAULT_OUTPUT_PATTERNS
        return
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        inp = data.get("input_patterns") or []
        out = data.get("output_patterns") or []
        _input_patterns = tuple(str(p) for p in inp if p) or _DEFAULT_INPUT_PATTERNS
        _output_patterns = tuple(str(p) for p in out if p) or _DEFAULT_OUTPUT_PATTERNS
    except Exception as ex:
        logger.warning("加载 sensitive_words.yaml 失败，使用内置列表: %s", ex)
        _input_patterns = _DEFAULT_INPUT_PATTERNS
        _output_patterns = _DEFAULT_OUTPUT_PATTERNS


def _matches(text: str, patterns: Tuple[str, ...]) -> Optional[str]:
    body = (text or "").strip()
    if not body:
        return None
    for pat in patterns:
        if re.search(pat, body, re.IGNORECASE):
            return pat
    return None


def check_sensitive_input(text: str) -> Optional[str]:
    """命中则返回匹配 pattern。"""
    return _matches(text, _input_patterns)


def check_sensitive_output(text: str) -> Optional[str]:
    return _matches(text, _output_patterns)


def content_safety_api_enabled() -> bool:
    return bool(os.getenv("CONTENT_SAFETY_API_URL", "").strip())


async def check_content_safety_api(
    text: str,
    *,
    direction: str = "input",
) -> Optional[bool]:
    """
    调用外部内容安全 API。
    返回 True=unsafe（应拦截），False=safe，None=未调用或 API 不可用（fail-open）。
    """
    url = os.getenv("CONTENT_SAFETY_API_URL", "").strip()
    if not url or not (text or "").strip():
        return None
    payload = {"text": text[:4000], "direction": direction}
    try:
        import httpx

        timeout = float(os.getenv("CONTENT_SAFETY_API_TIMEOUT_S", "5"))
        headers = {}
        api_key = os.getenv("CONTENT_SAFETY_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            if data.get("unsafe") is True:
                return True
            if data.get("safe") is False:
                return True
            if data.get("safe") is True or data.get("unsafe") is False:
                return False
        logger.warning("内容安全 API 响应无法解析: %s", type(data))
        return None
    except Exception as ex:
        logger.warning("内容安全 API 调用失败（fail-open）: %s", ex)
        return None


reload_sensitive_patterns()
