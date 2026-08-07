"""智能体层:supervisor-as-tools。

【supervisor-as-tools 是什么】
一个"编排总管"(supervisor)agent,把每个领域专家都当成一个【工具】挂在自己身上。
总管拿到主题后,自主判断该调哪几个专家、给每个专家派什么具体任务,然后(并行)调用它们,
最后把各专家的结论综合成报告。和"群里平等接力(swarm)""一层层往下分(hierarchical)"是不同模式。

【这里的专家工具长什么样】
每个专家工具 = 一个 wrapper 函数(make_expert_tool 造),内部干三件事:
    1. 进入时打 tool_call 事件(前端:总管→该专家 派发动画)
    2. 确定性联网检索一次(web_search,见 tool.py),把真实资料拿到手
    3. 让"专家 agent"基于这份真实资料做总结,返回时打 tool_done 事件(结论回流总管)
总管并行调多个专家时,这些 wrapper 并发执行,事件时间戳自然错开 —— 前端就能呈现"真并行"。
"""
import json

# ↓ MAF(Microsoft Agent Framework):pip 包 agent-framework-core / -openai,导入名 agent_framework
from agent_framework.openai import OpenAIChatCompletionClient
from .config import MODEL, BASE_URL, KEY
from .runtime import EVENT_Q, EXPERT_RESULTS, _ms
from .tool import fetch_for_expert, retry_for_expert, search_strategy_info
from .prompts import load_prompt, expert_instructions, summarize_user_message
from .llm_retry import run_with_retry

# Block 7 · 提示词(外置 backend/prompts/*.md)
SUP_INSTRUCTIONS = load_prompt("supervisor")
SYNTHESIZER_INSTRUCTIONS = load_prompt("synthesizer")
REPORT_TEMPLATE = load_prompt("report_template")

# DeepSeek 仅支持 /chat/completions,须用 ChatCompletionClient(非 Responses API 的 OpenAIChatClient)
client = OpenAIChatCompletionClient(model=MODEL, api_key=KEY, base_url=BASE_URL)

# ── 8 个半导体领域专家 worker ──
# 总管会按主题"挑相关的"调用(通常 3~7 个),不是每次都全调 —— 这正是 supervisor 的决策价值。
# 每条:tool=工具名(总管眼里的) / agent=agent 名 / label+icon=前端显示 / role+dims=该专家的身份与分析维度
WORKERS = [
    {"tool": "policy_expert",              "agent": "policy_analyst",              "label": "政策监管", "icon": "🏛️", "role": "政策与监管专家",       "dims": "国产化政策/出口管制/信创/合规与制裁规则"},
    {"tool": "manufacturing_expert",        "agent": "manufacturing_analyst",        "label": "制造产能", "icon": "🏭", "role": "制造与产能专家",       "dims": "晶圆制造/产能/制程节点/Foundry·OSAT"},
    {"tool": "design_ip_expert",            "agent": "design_ip_analyst",            "label": "设计IP",   "icon": "💡", "role": "设计/IP/EDA专家",      "dims": "Fabless/SoC/IP核/EDA工具国产化"},
    {"tool": "equipment_materials_expert", "agent": "equipment_materials_analyst", "label": "设备材料", "icon": "⚙️", "role": "设备与材料专家",       "dims": "半导体设备/材料/国产化率/供应链瓶颈"},
    {"tool": "competitor_expert",           "agent": "competitor_analyst",           "label": "竞争格局", "icon": "🏢", "role": "企业与竞争专家",       "dims": "头部企业/市场份额/商业模式/并购整合"},
    {"tool": "tech_roadmap_expert",         "agent": "tech_roadmap_analyst",         "label": "技术路线", "icon": "🔬", "role": "技术路线专家",         "dims": "先进制程/Chiplet/AI芯片/SiC·GaN等"},
    {"tool": "risk_supply_expert",          "agent": "risk_supply_analyst",          "label": "供应链",   "icon": "⚠️", "role": "供应链与地缘专家",     "dims": "断供风险/国产替代/制裁影响/供应链韧性"},
    {"tool": "investment_expert",           "agent": "investment_analyst",           "label": "投资政策", "icon": "💰", "role": "投资与产业政策专家",   "dims": "大基金三期/地方补贴/IPO/估值/个股"},
]

# 给总管看的工具简介(它据此判断该不该调某专家);也用于前端"点工具看说明"
TOOL_DESC = {
    "policy_expert":              "政策监管:国产化/出口管制/信创/合规(会联网检索)",
    "manufacturing_expert":        "制造产能:晶圆/制程/Foundry·OSAT(会联网检索)",
    "design_ip_expert":            "设计IP:Fabless/SoC/IP/EDA国产化(会联网检索)",
    "equipment_materials_expert": "设备材料:设备/材料/国产化率/瓶颈(会联网检索)",
    "competitor_expert":           "竞争格局:头部企业/份额/并购(会联网检索)",
    "tech_roadmap_expert":         "技术路线:先进制程/Chiplet/AI芯片/SiC·GaN(会联网检索)",
    "risk_supply_expert":          "供应链:断供/替代/制裁/韧性(会联网检索)",
    "investment_expert":           "投资政策:大基金/补贴/IPO/估值/个股(会联网检索;不构成投资建议)",
}


# 把每个专家实例化成一个 MAF agent(只负责推理总结,不自带搜索工具 —— 检索由 wrapper 确定性做)
EXPERTS = {
    w["tool"]: client.as_agent(name=w["agent"], instructions=expert_instructions(w["tool"]))
    for w in WORKERS
}


# 判定专家结论是否"实质无效"(检索到的资料不相关/不足时,模型常这么开头)
_INSUFFICIENT = ("无法基于", "不涉及", "未涉及", "无法获取", "没有相关", "无相关",
                 "均不涉及", "没有提供", "未提供", "无法分析", "抱歉", "未检索到")


def _is_insufficient(out: str) -> bool:
    return any(m in out for m in _INSUFFICIENT)


async def _summarize(expert, task: str, data: str, tool_name: str) -> str:
    """让专家 agent 基于给定资料做总结(单次,无工具循环 → 稳)。"""
    async def _call():
        r = await expert.run(
            summarize_user_message(task, data, tool_name),
            options={"max_tokens": 16000, "temperature": 0.3},
        )
        return getattr(r, "text", None) or str(r)

    return await run_with_retry(_call, label=f"expert:{tool_name}")


def make_expert_tool(w):
    """把一个专家包装成"总管可调用的函数工具"。

    标准流程: tool_call → 确定性检索 → expert.run(deepseek-v4-pro) → 无效则聚焦重搜 → tool_done
    investment_expert: 双 query(政策资金 + 个股估值) + 无效时聚焦大基金/PE 重搜
    """
    tool_name = w["tool"]
    expert = EXPERTS[tool_name]

    async def call_expert(task: str) -> str:
        q = EVENT_Q.get()
        if q is not None:
            await q.put({"event": "tool_call", "name": tool_name, "call_id": tool_name,
                         "arguments": json.dumps({"input": task}, ensure_ascii=False), "t": _ms()})
        try:
            data = await fetch_for_expert(tool_name, task)
            out = await _summarize(expert, task, data, tool_name)
            if _is_insufficient(out):
                more = await retry_for_expert(tool_name, task)
                out = await _summarize(
                    expert, task, data + "\n\n【补充检索】\n" + more, tool_name,
                )
        except Exception as e:
            out = f"(专家执行失败: {type(e).__name__}: {e})"
        er = EXPERT_RESULTS.get()
        if er is not None:
            er.append({"tool": tool_name, "output": str(out)})
        if q is not None:
            await q.put({"event": "tool_done", "name": tool_name, "output": str(out)[:700], "t": _ms()})
        return out

    call_expert.__name__ = tool_name
    call_expert.__doc__ = TOOL_DESC[tool_name]
    return call_expert


# 编排总管的系统提示词(Block 7 · backend/prompts/supervisor.md)

# 总管 = 一个挂了 8 个"专家工具"的 agent。这一行就是 supervisor-as-tools 的精髓。
supervisor = client.as_agent(
    name="research_supervisor",
    instructions=SUP_INSTRUCTIONS,
    tools=[make_expert_tool(w) for w in WORKERS],
)

# 无工具的综合器(Block 7 · backend/prompts/synthesizer.md)
synthesizer = client.as_agent(
    name="research_synthesizer",
    instructions=SYNTHESIZER_INSTRUCTIONS,
)


def agent_info_supervisor():
    """/api/agents 用:返回总管的提示词 + 工具列表(前端点总管节点时展示)。"""
    tools = [{"name": w["tool"], "description": TOOL_DESC[w["tool"]],
              "kind": "agent", "params": [{"name": "task", "type": "string"}]} for w in WORKERS]
    return {"name": "research_supervisor", "role": "编排总管 · supervisor", "tool": None,
            "instructions": SUP_INSTRUCTIONS, "tools": tools}


def agent_info_worker(w):
    """/api/agents 用:返回单个专家的提示词 + 检索策略 + web_search 工具。"""
    return {"name": w["agent"], "role": w["role"] + " · worker", "tool": w["tool"],
            "instructions": expert_instructions(w["tool"]),
            "search_strategy": search_strategy_info(w["tool"]),
            "tools": [{"name": "web_search",
                       "description": "ddgs 联网检索(由 tool.py SEARCH_STRATEGY 确定性执行,结果喂给专家总结)。",
                       "kind": "function", "params": [{"name": "query", "type": "string"}]}]}
