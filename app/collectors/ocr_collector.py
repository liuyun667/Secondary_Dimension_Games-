"""ocr_collector：截图兜底（浏览器读屏 / 上传截图）。

仅作为「没有导出工具时」的兜底：用户仍需自己翻页（浏览器不能模拟按键）。
"""
from __future__ import annotations

import base64

from .. import pipeline


def collect(game_row: dict, payload: dict) -> list[str]:
    image = payload.get("image", "")
    if not image:
        raise ValueError("缺少截图（payload.image, base64）")
    return pipeline.extract_lines(image_bytes=base64.b64decode(image))
