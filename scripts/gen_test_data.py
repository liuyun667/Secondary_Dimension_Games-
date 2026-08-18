"""测试账户数据生成 CLI（v2）：实时生成 66 角色/150 武器/1000 圣遗物/400 材料。

用法：python scripts/gen_test_data.py [--session test_demo] [--game 1]
（网页「导入测试数据」按钮等价调用 POST /api/v1/test-data/generate）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import test_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="test_demo")
    ap.add_argument("--game", type=int, default=1)
    args = ap.parse_args()
    n = test_data.generate_test_account(args.session, args.game)
    print(f"已实时生成测试账户「{args.session}」：{n} 项资产"
          f"（66 角色 / 150 武器 / 1000 圣遗物 / 400 材料）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
