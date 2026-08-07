"""项目路径解析。"""

from pathlib import Path

_PROJECT_ROOT: Path | None = None


def get_project_root() -> Path:
    """定位仓库根目录（含 config/、data/）。"""
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT

    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "config").is_dir() and (candidate / "src").is_dir():
        _PROJECT_ROOT = candidate
        return _PROJECT_ROOT

    cwd = Path.cwd()
    if (cwd / "config").is_dir():
        _PROJECT_ROOT = cwd
        return _PROJECT_ROOT

    raise FileNotFoundError("无法定位项目根目录（需含 config/ 与 src/）")
