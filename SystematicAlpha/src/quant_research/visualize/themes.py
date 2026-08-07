"""图表主题：中文字体与配色。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

# 分类配色
COLORS = {
    "primary": "#2563eb",
    "secondary": "#64748b",
    "positive": "#16a34a",
    "negative": "#dc2626",
    "accent": "#f59e0b",
    "current": "#2563eb",
    "prior": "#94a3b8",
}

_CJK_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]


def setup_chinese_font() -> None:
    """配置 matplotlib 中文字体，避免乱码。"""
    for font_path in _CJK_FONT_CANDIDATES:
        if font_path.is_file():
            plt.rcParams["font.sans-serif"] = [font_path.stem, "Arial Unicode MS", "SimHei"]
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "Noto Sans SC"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 150
    plt.rcParams["savefig.bbox"] = "tight"
