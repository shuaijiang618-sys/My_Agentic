"""PDF 路径解析。"""

from __future__ import annotations

from pathlib import Path


def resolve_pdf(pdf: str, project_root: Path) -> Path:
    """解析 PDF：绝对路径 → data/input → data/ 根 → data 下递归匹配。"""
    path = Path(pdf)
    if path.is_file():
        return path.resolve()

    candidates = [
        project_root / "data" / "input" / pdf,
        project_root / "data" / pdf,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    name = Path(pdf).name
    data_dir = project_root / "data"
    if data_dir.is_dir():
        matches = sorted(data_dir.rglob(name))
        if matches:
            return matches[0].resolve()

    raise FileNotFoundError(
        f"找不到 PDF: {pdf}\n"
        f"  可放在 data/input/ 下，或传入绝对路径"
    )
