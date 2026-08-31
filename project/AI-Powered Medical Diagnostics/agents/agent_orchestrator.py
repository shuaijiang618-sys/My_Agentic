"""
医疗 Multi-Agent 编排：导诊 / 报告解释 / 紧急 / 泛医学科普。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.intent_recognizer import IntentCategory, IntentRecognizer, UrgencyLevel
from core.llm_utils import create_message, extract_text_content
from core.medical_security import EMERGENCY_RESPONSE

logger = logging.getLogger(__name__)


class AgentType(Enum):
    TRIAGE = "triage"
    REPORT = "report"
    EMERGENCY = "emergency"
    GENERAL = "general"
    GREETING = "greeting"


@dataclass
class AgentStats:
    total: int = 0
    success: int = 0
    total_ms: float = 0.0
    monitor_penalty: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.total if self.total else 0.0

    def routing_score(self) -> float:
        latency_score = 1.0 / (1.0 + self.avg_ms / 1000)
        return (self.success_rate * 0.7 + latency_score * 0.3) * max(
            0.0, 1.0 - self.monitor_penalty,
        )


@dataclass
class AgentResponse:
    agent_type: AgentType
    content: str
    success: bool
    latency_ms: float = 0.0
    escalate: bool = False


@dataclass
class Request:
    message: str
    user_id: str
    conv_id: str
    context: str = ""
    history: Optional[List[Dict[str, str]]] = None
    intent: Optional[IntentCategory] = None
    urgency: Optional[UrgencyLevel] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class OrchestratorResult:
    request_id: str
    response: str
    agent_type: AgentType
    intent: Optional[IntentCategory]
    escalated: bool = False
    emergency: bool = False
    latency_ms: float = 0.0
    agent_success: bool = True


class BaseAgent:
    agent_type: AgentType

    def __init__(self, client: AsyncAnthropic, model: str, skill_manager: Optional[Any] = None):
        self._client = client
        self._model = model
        self._skill_manager = skill_manager
        self.stats = AgentStats()

    def _base_system_prompt(self) -> str:
        from core.prompt_registry import get_registry
        return get_registry().agent_system(self.agent_type.value)

    async def handle(self, req: Request) -> AgentResponse:
        t0 = time.monotonic()
        self.stats.total += 1
        try:
            content = await self._call_llm(req)
            ms = (time.monotonic() - t0) * 1000
            self.stats.success += 1
            self.stats.total_ms += ms
            return AgentResponse(
                agent_type=self.agent_type,
                content=content,
                success=True,
                latency_ms=ms,
            )
        except Exception as ex:
            ms = (time.monotonic() - t0) * 1000
            self.stats.total_ms += ms
            logger.error("%s 处理失败: %s", self.agent_type.value, ex)
            return AgentResponse(
                agent_type=self.agent_type,
                content="抱歉，暂时无法处理您的问题，请稍后重试或前往医疗机构咨询。",
                success=False,
                latency_ms=ms,
            )

    async def _call_llm(self, req: Request) -> str:
        from core.prompt_registry import get_registry

        reg = get_registry()

        def _clean(s: str) -> str:
            return s.encode("utf-8", errors="ignore").decode("utf-8")

        messages: List[Dict[str, str]] = []
        if req.context:
            messages.append({
                "role": "user",
                "content": f"{reg.background_prefix}\n{_clean(req.context)}",
            })
            messages.append({"role": "assistant", "content": reg.context_ack})
        messages.append({"role": "user", "content": _clean(req.message)})

        resp = await create_message(
            self._client,
            stage=f"agent_{self.agent_type.value}",
            model=self._model,
            max_tokens=1024,
            system=self._build_system_prompt(req),
            messages=messages,
        )
        return extract_text_content(resp.content)

    async def _call_llm_structured(self, req: Request, *, schema_key: str) -> str:
        """JSON 结构化输出 + Markdown 模板渲染；解析失败自动重试 1 次。"""
        from core.prompt_registry import get_registry
        from core.structured_response import build_agent_response, build_retry_user_message

        reg = get_registry()
        if not reg.structured_output_enabled(schema_key):
            return await self._call_llm(req)

        def _clean(s: str) -> str:
            return s.encode("utf-8", errors="ignore").decode("utf-8")

        messages: List[Dict[str, str]] = []
        if req.context:
            messages.append({
                "role": "user",
                "content": f"{reg.background_prefix}\n{_clean(req.context)}",
            })
            messages.append({"role": "assistant", "content": reg.context_ack})
        messages.append({"role": "user", "content": _clean(req.message)})

        system = self._build_system_prompt(req)
        instruction = reg.structured_output_instruction(schema_key)
        if instruction:
            system = f"{system}\n\n{instruction}"

        required_fields = reg.structured_required_fields(schema_key)
        template_text = reg.response_template(schema_key)

        async def _attempt(msgs: List[Dict[str, str]], *, stage_suffix: str) -> tuple[str, str, bool]:
            resp = await create_message(
                self._client,
                stage=f"agent_{self.agent_type.value}{stage_suffix}",
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=msgs,
            )
            raw_text = extract_text_content(resp.content)
            rendered_text, structured_ok = build_agent_response(
                schema_key,
                raw_text,
                template_text=template_text,
                required_fields=required_fields,
                fallback_to_raw=True,
            )
            return raw_text, rendered_text, structured_ok

        raw, rendered, ok = await _attempt(messages, stage_suffix="")
        if ok:
            return rendered

        logger.info(
            "%s 结构化首次失败，重试一次 schema=%s",
            self.agent_type.value,
            schema_key,
        )
        retry_messages = list(messages)
        retry_messages.append({"role": "assistant", "content": raw})
        retry_messages.append({
            "role": "user",
            "content": build_retry_user_message(required_fields),
        })
        _raw2, rendered2, ok2 = await _attempt(retry_messages, stage_suffix="_retry")
        if ok2:
            logger.info("%s 结构化重试成功 schema=%s", self.agent_type.value, schema_key)
            return rendered2

        logger.info(
            "%s 结构化重试仍失败，回退 raw/部分字段 schema=%s",
            self.agent_type.value,
            schema_key,
        )
        return rendered2 or rendered

    def _build_system_prompt(self, req: Request) -> str:
        base = self._base_system_prompt()
        if self._skill_manager is None:
            return base
        skill_prompt = self._skill_manager.prompt_for(
            req.message, self.agent_type.value, user_id=req.user_id,
        )
        if not skill_prompt:
            return base
        return f"{base}\n\n[动态 Skills]\n{skill_prompt}"


class TriageAgent(BaseAgent):
    agent_type = AgentType.TRIAGE

    async def _call_llm(self, req: Request) -> str:
        return await self._call_llm_structured(req, schema_key="triage")


class ReportInterpretationAgent(BaseAgent):
    agent_type = AgentType.REPORT

    async def _call_llm(self, req: Request) -> str:
        return await self._call_llm_structured(req, schema_key="report")


class GeneralMedicalAgent(BaseAgent):
    agent_type = AgentType.GENERAL

    async def _call_llm(self, req: Request) -> str:
        return await self._call_llm_structured(req, schema_key="general")


class EmergencyAgent(BaseAgent):
    agent_type = AgentType.EMERGENCY

    async def handle(self, req: Request) -> AgentResponse:
        self.stats.total += 1
        self.stats.success += 1
        return AgentResponse(
            agent_type=self.agent_type,
            content=EMERGENCY_RESPONSE,
            success=True,
            escalate=True,
            latency_ms=0.0,
        )


class GreetingAgent(BaseAgent):
    """纯寒暄：规则模板，不调用 LLM。"""

    agent_type = AgentType.GREETING

    async def handle(self, req: Request) -> AgentResponse:
        from core.prompt_registry import get_registry

        self.stats.total += 1
        self.stats.success += 1
        return AgentResponse(
            agent_type=self.agent_type,
            content=get_registry().security("greeting"),
            success=True,
            latency_ms=0.0,
        )


class AgentOrchestrator:
    _INTENT_ROUTING: Dict[IntentCategory, AgentType] = {
        IntentCategory.EMERGENCY: AgentType.EMERGENCY,
        IntentCategory.GREETING: AgentType.GREETING,
        IntentCategory.TRIAGE: AgentType.TRIAGE,
        IntentCategory.REPORT_INTERPRET: AgentType.REPORT,
        IntentCategory.GENERAL_MEDICAL: AgentType.GENERAL,
    }

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        skill_manager: Optional[Any] = None,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncAnthropic(**kwargs)
        self._intent_recognizer = IntentRecognizer(
            api_key=api_key, base_url=base_url, model=model,
        )
        self._skill_manager = skill_manager
        self._pool: Dict[AgentType, List[BaseAgent]] = {
            AgentType.TRIAGE: [TriageAgent(client, model, skill_manager)],
            AgentType.REPORT: [ReportInterpretationAgent(client, model, skill_manager)],
            AgentType.GENERAL: [GeneralMedicalAgent(client, model, skill_manager)],
            AgentType.EMERGENCY: [EmergencyAgent(client, model, skill_manager)],
            AgentType.GREETING: [GreetingAgent(client, model, skill_manager)],
        }

    def set_skill_manager(self, skill_manager: Optional[Any]) -> None:
        self._skill_manager = skill_manager
        for agents in self._pool.values():
            for agent in agents:
                agent._skill_manager = skill_manager

    async def run(self, req: Request) -> OrchestratorResult:
        t0 = time.monotonic()
        if req.intent is None:
            intent_result = await self._intent_recognizer.recognize(req.message, history=req.history)
            req.intent = intent_result.intent
            req.urgency = intent_result.urgency

        agent_type = self._route(req.intent, req.urgency)
        response = await self._execute(req, agent_type)

        emergency = req.intent == IntentCategory.EMERGENCY or agent_type == AgentType.EMERGENCY
        escalated = (
            emergency
            or response.escalate
            or req.urgency == UrgencyLevel.CRITICAL
        )

        return OrchestratorResult(
            request_id=req.request_id,
            response=response.content,
            agent_type=response.agent_type,
            intent=req.intent,
            escalated=escalated,
            emergency=emergency,
            latency_ms=(time.monotonic() - t0) * 1000,
            agent_success=response.success,
        )

    def _route(
        self, intent: Optional[IntentCategory], urgency: Optional[UrgencyLevel],
    ) -> AgentType:
        if urgency == UrgencyLevel.CRITICAL or intent == IntentCategory.EMERGENCY:
            return AgentType.EMERGENCY
        if intent and intent in self._INTENT_ROUTING:
            target = self._INTENT_ROUTING[intent]
            if self._pool.get(target):
                return target
        return AgentType.GENERAL

    def _best_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        agents = self._pool.get(agent_type, [])
        if not agents:
            return None
        return max(agents, key=lambda a: a.stats.routing_score())

    async def _execute(self, req: Request, agent_type: AgentType) -> AgentResponse:
        agent = self._best_agent(agent_type) or self._best_agent(AgentType.GENERAL)
        if agent is None:
            return AgentResponse(
                agent_type=AgentType.GENERAL,
                content="服务暂时不可用，请前往医疗机构咨询。",
                success=False,
            )
        response = await agent.handle(req)
        if not response.success and agent_type != AgentType.GENERAL:
            fallback = self._best_agent(AgentType.GENERAL)
            if fallback:
                response = await fallback.handle(req)
        return response

    def get_stats(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for agent_type, agents in self._pool.items():
            for i, agent in enumerate(agents):
                key = f"{agent_type.value}_{i}"
                result[key] = {
                    "total": agent.stats.total,
                    "success_rate": round(agent.stats.success_rate, 3),
                    "avg_ms": round(agent.stats.avg_ms, 1),
                }
        return result
