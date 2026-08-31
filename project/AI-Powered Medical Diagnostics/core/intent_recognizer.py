"""
医疗导诊意图识别 — 三路融合（LLM + Embedding + 关键词）。

意图：导诊、报告解释、紧急症状、泛医学科普、问候、越界。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.llm_utils import create_message, extract_text_content
from core.medical_security import detect_emergency

logger = logging.getLogger(__name__)


class IntentCategory(Enum):
    TRIAGE           = "triage"
    REPORT_INTERPRET = "report_interpret"
    EMERGENCY        = "emergency"
    GENERAL_MEDICAL  = "general_medical"
    GREETING         = "greeting"
    OFF_TOPIC        = "off_topic"
    OTHER            = "other"


class UrgencyLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class IntentResult:
    intent: IntentCategory
    confidence: float
    urgency: UrgencyLevel
    entities: Dict[str, List[str]]
    reasoning: str
    latency_ms: float


_TEMPLATES: Dict[IntentCategory, List[str]] = {
    IntentCategory.TRIAGE: [
        "最近三天肚子胀还恶心，应该挂什么科？",
        "持续咳嗽有痰，去哪个科室看？",
    ],
    IntentCategory.REPORT_INTERPRET: [
        "体检 ALT 52 偏高是什么意思？",
        "血常规里中性粒细胞比例升高代表什么？",
    ],
    IntentCategory.EMERGENCY: [
        "胸口很痛喘不上气怎么办？",
        "家人突然意识不清了",
    ],
    IntentCategory.GENERAL_MEDICAL: [
        "医院怎么预约挂号？",
        "心内科主要看什么病？",
    ],
    IntentCategory.GREETING: ["你好", "您好"],
    IntentCategory.OFF_TOPIC: ["帮我写 python 代码", "今天天气怎么样"],
}

_URGENCY_KEYWORDS = {
    UrgencyLevel.CRITICAL: ["紧急", "马上", "立刻", "120"],
    UrgencyLevel.HIGH: ["今天", "尽快", "突然"],
}


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class IntentRecognizer:
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.45,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**kwargs)
        self.model = model
        self.threshold = confidence_threshold
        self._embedding_enabled = not bool(base_url)
        self._tpl_embeddings: Dict[IntentCategory, List[List[float]]] = {}
        self._cache: Dict[str, IntentResult] = {}

    async def recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentResult:
        if detect_emergency(message):
            return IntentResult(
                intent=IntentCategory.EMERGENCY,
                confidence=1.0,
                urgency=UrgencyLevel.CRITICAL,
                entities={"symptom": [message[:100]]},
                reasoning="规则命中紧急症状",
                latency_ms=0.0,
            )

        from core.medical_security import is_greeting_only

        if is_greeting_only(message):
            return IntentResult(
                intent=IntentCategory.GREETING,
                confidence=1.0,
                urgency=UrgencyLevel.LOW,
                entities={},
                reasoning="规则命中寒暄",
                latency_ms=0.0,
            )

        key = self._clean_text(message)[:200]
        if key in self._cache:
            return self._cache[key]

        t0 = time.monotonic()
        llm_task = asyncio.create_task(self._llm_recognize(message, history))
        emb_task = (
            asyncio.create_task(self._embedding_recognize(message))
            if self._embedding_enabled else None
        )
        pat = self._pattern_recognize(message)

        if emb_task:
            llm, emb = await asyncio.gather(llm_task, emb_task)
        else:
            llm = await llm_task
            emb = {"intent": IntentCategory.OTHER, "confidence": 0.0}

        intent = self._vote(llm, emb, pat)
        entities = await self._extract_entities(message)
        urgency = self._urgency(message, intent)

        result = IntentResult(
            intent=intent,
            confidence=float(llm.get("confidence", 0.5)),
            urgency=urgency,
            entities=entities,
            reasoning=str(llm.get("reasoning", "")),
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        if len(self._cache) >= 500:
            for k in list(self._cache)[:250]:
                del self._cache[k]
        self._cache[key] = result
        return result

    async def _llm_recognize(
        self, message: str, history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        examples = "\n".join(
            f'  消息: "{t}" → 意图: {cat.value}'
            for cat, tpls in _TEMPLATES.items()
            for t in tpls[:1]
        )
        ctx = ""
        if history:
            ctx = "\n最近对话:\n" + "\n".join(
                f"  {m.get('role', 'user')}: {m.get('content', '')[:80]}"
                for m in history[-3:]
            )
        prompt = f"""你是医疗导诊意图分析专家。判断用户意图，返回 JSON。

示例:
{examples}
{ctx}
用户消息: "{self._clean_text(message)}"

可选意图: {", ".join(c.value for c in IntentCategory)}

返回格式: {{"intent": "<意图值>", "confidence": <0-1>, "reasoning": "<一句话>"}}"""
        try:
            resp = await create_message(
                self.client,
                stage="intent",
                model=self.model, max_tokens=256, temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            try:
                data["intent"] = IntentCategory(data["intent"])
            except ValueError:
                data["intent"] = IntentCategory.OTHER
            return data
        except Exception as ex:
            logger.warning("LLM 意图识别失败: %s", ex)
            return {"intent": IntentCategory.OTHER, "confidence": 0.0, "failed": True}

    async def _embedding_recognize(self, message: str) -> Dict[str, Any]:
        try:
            await self._load_template_embeddings()
            msg_vec = await self._embed_text(message)
            best_cat, best_score = IntentCategory.OTHER, 0.0
            for cat, vecs in self._tpl_embeddings.items():
                score = max(_cosine(msg_vec, v) for v in vecs)
                if score > best_score:
                    best_score, best_cat = score, cat
            return {"intent": best_cat, "confidence": best_score}
        except Exception as ex:
            logger.warning("Embedding 识别失败: %s", ex)
            return {"intent": IntentCategory.OTHER, "confidence": 0.0}

    def _pattern_recognize(self, message: str) -> Dict[str, Any]:
        msg = message.lower()
        patterns = {
            IntentCategory.EMERGENCY: ["胸痛", "喘不上", "意识不清", "昏迷", "120"],
            IntentCategory.REPORT_INTERPRET: [
                "alt", "ast", "指标", "偏高", "偏低", "体检", "化验", "mmol", "报告",
            ],
            IntentCategory.TRIAGE: ["挂什么科", "哪个科", "看什么科", "导诊", "科室"],
            IntentCategory.GENERAL_MEDICAL: ["挂号", "预约", "流程", "门诊", "急诊"],
            IntentCategory.GREETING: ["你好", "您好", "hi", "hello"],
            IntentCategory.OFF_TOPIC: ["python", "代码", "股票", "天气"],
        }
        best_cat, best_score = IntentCategory.OTHER, 0.0
        for cat, kws in patterns.items():
            hits = sum(1 for kw in kws if kw in msg)
            if hits:
                score = hits / len(kws)
                if score > best_score:
                    best_score, best_cat = score, cat
        return {"intent": best_cat, "confidence": best_score}

    def _vote(self, llm: Dict, emb: Dict, pat: Dict) -> IntentCategory:
        if llm.get("failed"):
            return pat["intent"] if pat.get("confidence", 0) > 0 else IntentCategory.OTHER
        weights = (
            [(llm, 0.7), (emb, 0.2), (pat, 0.1)]
            if self._embedding_enabled
            else [(llm, 0.85), (pat, 0.15)]
        )
        scores: Dict[IntentCategory, float] = {}
        for result, w in weights:
            cat = result.get("intent", IntentCategory.OTHER)
            conf = float(result.get("confidence", 0.0))
            scores[cat] = scores.get(cat, 0.0) + w * conf
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return best if scores[best] >= self.threshold else IntentCategory.OTHER

    async def _extract_entities(self, message: str) -> Dict[str, List[str]]:
        prompt = f"""从医疗咨询消息中提取实体，返回 JSON（无则为空列表）:
消息: "{self._clean_text(message)}"
格式: {{"symptom":[],"lab_item":[],"value":[],"duration":[],"department_hint":[]}}"""
        try:
            resp = await create_message(
                self.client,
                stage="intent_entities",
                model=self.model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("{"), raw.rfind("}") + 1
            return json.loads(raw[s:e])
        except Exception:
            return {
                "symptom": [], "lab_item": [], "value": [],
                "duration": [], "department_hint": [],
            }

    def _urgency(self, message: str, intent: IntentCategory) -> UrgencyLevel:
        if intent == IntentCategory.EMERGENCY:
            return UrgencyLevel.CRITICAL
        msg = message.lower()
        for level, kws in _URGENCY_KEYWORDS.items():
            if any(kw in msg for kw in kws):
                return level
        if intent == IntentCategory.TRIAGE:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    async def _load_template_embeddings(self) -> None:
        missing = [cat for cat in _TEMPLATES if cat not in self._tpl_embeddings]
        if not missing:
            return
        all_texts = [t for cat in missing for t in _TEMPLATES[cat]]
        vecs = [self._local_embedding(t) for t in all_texts]
        idx = 0
        for cat in missing:
            n = len(_TEMPLATES[cat])
            self._tpl_embeddings[cat] = vecs[idx: idx + n]
            idx += n

    async def _embed_text(self, text: str) -> List[float]:
        return self._local_embedding(text)

    @staticmethod
    def _local_embedding(text: str, dims: int = 256) -> List[float]:
        normalized = text.lower().strip()
        vec = [0.0] * dims
        tokens = set()
        for n in (1, 2, 3):
            if len(normalized) >= n:
                tokens.update(normalized[i:i + n] for i in range(len(normalized) - n + 1))
        if not tokens:
            tokens.add(normalized)
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return vec

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")
