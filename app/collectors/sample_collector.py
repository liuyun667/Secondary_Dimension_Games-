"""sample_collector：示例账户（演示/测试用），与「导入示例账户」共用数据。"""
from __future__ import annotations

from .. import sample_data


def collect(game_row: dict, payload: dict) -> list[str]:
    return sample_data.lines_for(game_row["name"])
