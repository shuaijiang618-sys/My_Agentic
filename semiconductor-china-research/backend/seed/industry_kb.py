"""Block 3B · industry_kb.db 种子数据与初始化脚本。

用法(项目根目录):
    python -m backend.seed.industry_kb
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 允许 python -m backend.seed.industry_kb 直接运行
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import INDUSTRY_KB_DB
from backend.kb import init_schema

# 30 只上市半导体标的(附录 · 种子清单)
LISTED = [
    # 晶圆制造 / IDM / 封测
    ("688981.SH", "中芯国际", "SSE", "foundry", "A股晶圆代工龙头"),
    ("1347.HK", "华虹半导体", "HK", "foundry", "港股晶圆代工"),
    ("688347.SH", "华虹公司", "SSE", "foundry", "华虹半导体 A 股"),
    ("600584.SH", "长电科技", "SSE", "osat", "封测龙头"),
    ("002156.SZ", "通富微电", "SZSE", "osat", "封测"),
    ("603005.SH", "晶方科技", "SSE", "osat", "封测/TSV"),
    # 设备
    ("002371.SZ", "北方华创", "SZSE", "equipment", "刻蚀/薄膜/热处理等设备"),
    ("688012.SH", "中微公司", "SSE", "equipment", "刻蚀/CVD"),
    ("688082.SH", "盛美上海", "SSE", "equipment", "清洗/电镀"),
    ("688037.SH", "芯源微", "SSE", "equipment", "涂胶显影/清洗"),
    ("688200.SH", "华峰测控", "SSE", "equipment", "测试设备"),
    ("300604.SZ", "长川科技", "SZSE", "equipment", "测试/分选"),
    ("688409.SH", "富创精密", "SSE", "equipment", "零部件/腔体"),
    # 材料
    ("688126.SH", "沪硅产业", "SSE", "material", "大硅片"),
    ("605358.SH", "立昂微", "SSE", "material", "硅片/功率器件"),
    ("688019.SH", "安集科技", "SSE", "material", "CMP/光刻胶配套"),
    ("300666.SZ", "江丰电子", "SZSE", "material", "溅射靶材"),
    ("688138.SH", "清溢光电", "SSE", "material", "掩膜版"),
    # 设计 / EDA / IP
    ("688256.SH", "寒武纪", "SSE", "fabless_ai", "AI 芯片"),
    ("688008.SH", "澜起科技", "SSE", "fabless", "内存接口芯片"),
    ("688396.SH", "华润微", "SSE", "idm", "IDM/功率"),
    ("688521.SH", "芯原股份", "SSE", "ip", "IP/SiP"),
    ("603986.SH", "兆易创新", "SSE", "fabless", "Nor Flash/MCU"),
    ("301269.SZ", "华大九天", "SZSE", "eda", "国产 EDA"),
    ("688206.SH", "概伦电子", "SSE", "eda", "国产 EDA"),
    # 功率 / 第三代半导体
    ("600460.SH", "士兰微", "SSE", "power_idm", "功率 IDM"),
    ("688187.SH", "时代电气", "SSE", "power", "轨交/功率模块"),
    ("688234.SH", "天岳先进", "SSE", "sic", "SiC 衬底"),
    ("688711.SH", "宏微科技", "SSE", "power_module", "功率模块"),
    # 港股
    ("981.HK", "中芯国际", "HK", "foundry", "港股中芯"),
]

FUND_EVENTS = [
    ("2024-05", "国家集成电路产业投资基金三期", "设立", "3440亿元(公开报道)", "集成电路全产业链",
     "三期基金注册成立,投向覆盖设计、制造、封测、设备材料等;具体投资以官方披露为准",
     "https://www.gov.cn/"),
    ("2023-09", "国家集成电路产业投资基金二期", "投资", "未披露", "设备/材料/制造多家",
     "二期持续投资半导体设备材料等领域;被投企业名单以公开披露为准", ""),
    ("2022-03", "地方产业基金(示例)", "投资", "未披露", "区域晶圆/封测项目",
     "多地设立集成电路产业基金支持本地项目;金额与项目以各地公告为准", ""),
]

FACILITIES = [
    ("中芯国际", "北京晶圆厂", "北京", "28nm及以上", "量产", "在产", ""),
    ("中芯国际", "上海晶圆厂", "上海", "14nm/28nm", "量产/扩产", "在产", ""),
    ("华虹半导体", "无锡晶圆厂", "江苏无锡", "55/40/28nm", "量产", "在产", ""),
    ("长电科技", "江阴封测基地", "江苏江阴", "—", "先进封装", "在产", ""),
    ("通富微电", "南通封测基地", "江苏南通", "—", "CPU/GPU 封测", "在产", ""),
]

POLICY_EVENTS = [
    ("2024-01", "美国 BIS 半导体出口管制更新(示例)", "美国商务部 BIS", "export_control",
     "对先进计算芯片、半导体制造设备等实施出口限制;具体条目以联邦公报为准", ""),
    ("2023-08", "集成电路企业研发费用加计扣除政策延续", "财政部/税务总局", "subsidy",
     "集成电路企业研发费用可按政策享受加计扣除;以当年财税文件为准", ""),
    ("2022-01", "「十四五」数字经济发展规划(集成电路章节)", "国务院", "industry_plan",
     "强调集成电路产业自主可控与产业链供应链安全", ""),
]


def seed(conn: sqlite3.Connection) -> dict[str, int]:
    init_schema(conn)
    conn.execute("DELETE FROM listed_semiconductor")
    conn.execute("DELETE FROM fund_events")
    conn.execute("DELETE FROM facilities")
    conn.execute("DELETE FROM policy_events")

    conn.executemany(
        "INSERT INTO listed_semiconductor(symbol,name,exchange,segment,notes) VALUES(?,?,?,?,?)",
        LISTED,
    )
    conn.executemany(
        """INSERT INTO fund_events(event_date,fund_name,event_type,amount,target,summary,source_url)
           VALUES(?,?,?,?,?,?,?)""",
        FUND_EVENTS,
    )
    conn.executemany(
        """INSERT INTO facilities(company,facility_name,location,process_node,capacity,status,source_url)
           VALUES(?,?,?,?,?,?,?)""",
        FACILITIES,
    )
    conn.executemany(
        """INSERT INTO policy_events(policy_date,title,issuer,category,summary,source_url)
           VALUES(?,?,?,?,?,?)""",
        POLICY_EVENTS,
    )
    conn.commit()
    return {
        "listed_semiconductor": len(LISTED),
        "fund_events": len(FUND_EVENTS),
        "facilities": len(FACILITIES),
        "policy_events": len(POLICY_EVENTS),
    }


def main() -> None:
    conn = sqlite3.connect(INDUSTRY_KB_DB)
    counts = seed(conn)
    conn.close()
    print(f"✅ industry_kb.db 已初始化 @ {INDUSTRY_KB_DB}")
    for k, v in counts.items():
        print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
