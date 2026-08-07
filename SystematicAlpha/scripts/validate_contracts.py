#!/usr/bin/env python3
"""离线校验 data/runs 下 JSON 是否符合 schemas/ 契约。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    # TODO: 加载 schemas/ 并对 data/runs/*/ 下 JSON 做 jsonschema 校验
    _ = root / "schemas"
    print("validate_contracts: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
