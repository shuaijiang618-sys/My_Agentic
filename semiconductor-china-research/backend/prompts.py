"""Block 7 · 提示词加载器。单一真相源: backend/prompts/*.md"""
from pathlib import Path

from .config import PROMPTS

EXPERT_TOOLS = (
    "policy_expert",
    "manufacturing_expert",
    "design_ip_expert",
    "equipment_materials_expert",
    "competitor_expert",
    "tech_roadmap_expert",
    "risk_supply_expert",
    "investment_expert",
)


def load_prompt(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"提示词文件不存在: {path}")
    return path.read_text(encoding="utf-8").strip()


def expert_instructions(tool: str) -> str:
    if tool not in EXPERT_TOOLS:
        raise KeyError(f"未知专家 tool: {tool}")
    return load_prompt(tool)


def summarize_user_message(task: str, data: str, tool: str) -> str:
    """专家 run 的用户消息(任务 + 资料)。"""
    return (
        f"研究任务:{task}\n\n"
        f"以下是检索到的真实资料:\n{data}\n\n"
        f"请基于资料给出分析,内容详实,最长可到 4096 字(资料少就实事求是写短,不要注水),"
        f"尽量保留具体数字/名称/版本/时间/政策名/公司名等事实细节。直接作答。"
    )
