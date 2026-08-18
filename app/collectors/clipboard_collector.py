"""clipboard_collector：从剪贴板/粘贴框导入。

支持两种内容：
- 一段 JSON（同 file_collector 格式）；
- 纯文本行（每行一条，如 "胡桃 Lv.90"、"炽烈的炎之魔女（生命值）花"）。
"""
from __future__ import annotations

import json

from . import file_collector


def collect(game_row: dict, payload: dict) -> list[str]:
    text = (payload.get("text") or "").strip()
    if not text:
        raise ValueError("缺少粘贴内容（payload.text）")
    if text.lstrip().startswith(("{", "[")):
        try:
            return file_collector.collect(game_row, {"content": text})
        except json.JSONDecodeError:
            pass  # 不是 JSON，按文本行处理
    return [ln.strip() for ln in text.splitlines() if ln.strip()]
