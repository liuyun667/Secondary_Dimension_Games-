"""采集插件系统：把「如何拿到玩家资产」从「识别管线」中解耦。

架构（参考莫娜占卜铺的「采集与计算分离」思路）：

    采集层（在用户设备上，可操作游戏）          导入层（本 Web 服务）
    ┌──────────────────────────┐   导出 JSON    ┌──────────────────────┐
    │ 伴生导出工具（Amenoma 等）│ ────────────► │ file_collector        │──┐
    │ 自动翻页+截图识别，零手点 │   / 剪贴板     │ clipboard_collector   │  │ 统一转成
    └──────────────────────────┘               │ sample_collector(示例) │  │ 文本行
    ┌──────────────────────────┐   截图/文本    │ ocr_collector(兜底)    │  │
    │ 浏览器读屏 / 上传 / 粘贴  │ ────────────► └──────────────────────┘  │
    └──────────────────────────┘                                        ▼
                                               pipeline.analyze_lines（实体链接→结构化）

- 采集插件只需产出一份「文本行」，识别管线完全复用；
- 新增采集来源 = 注册一个新插件，不动识别/推荐代码。
"""
from __future__ import annotations

from . import (auto_collector, clipboard_collector, file_collector,
               ocr_collector, sample_collector)
from .. import database as db, pipeline

# 插件注册表：method -> 采集函数(game_row, payload) -> list[str] 文本行
# 例外：auto 直接返回结构化资产（auto_collector.collect_assets）
COLLECTORS = {
    "file": file_collector.collect,           # 导入导出文件（JSON，推荐，零翻页）
    "clipboard": clipboard_collector.collect, # 粘贴导出数据 / 文本行
    "sample": sample_collector.collect,       # 示例账户（演示）
    "ocr": ocr_collector.collect,             # 截图兜底（浏览器读屏/上传）
    "auto": auto_collector.collect_assets,    # 伴生工具自动点击结果（结构化直转）
}


def run_collector(game_id: int, method: str, payload: dict | None = None) -> dict:
    """执行采集插件 → 文本行 → 走统一识别管线 → 资产列表。"""
    if method not in COLLECTORS:
        raise KeyError(f"未知采集方式: {method}（可选 {'/'.join(COLLECTORS)}）")
    game = db.query_one("SELECT * FROM game WHERE id=?", (game_id,))
    if not game:
        raise ValueError(f"游戏不存在: {game_id}")
    if method == "auto":     # 结构化结果直转，不经文本行/二次解析
        return COLLECTORS[method](game, payload or {})
    lines = COLLECTORS[method](game, payload or {})
    return pipeline.analyze_lines(lines, game_id, session_id="collect")
