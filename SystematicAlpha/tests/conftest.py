"""pytest 配置与共享 fixtures。"""

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def fixtures_dir(project_root: Path) -> Path:
    return project_root / "data" / "fixtures"
