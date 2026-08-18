"""auto_collector：直接导入「伴生工具自动点击」采集的结构化结果。

auto_export.py 输出的 JSON 与 file_collector 的通用格式字段不同（artifacts 用
set/slot/main/main_value/level），且卡片已是结构化数据，无需再走文本行二次解析，
这里直接转换为资产 dict（与 pipeline.analyze_lines 输出同构，graduate/advice 直接可用）。

payload: {"path": "data/artifacts_auto.json"}（限定项目目录内）
"""
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def collect_assets(game_row: dict, payload: dict) -> dict:
    path = payload.get("path", "")
    if not path:
        raise ValueError("缺少采集结果路径（payload.path）")
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    if not str(p).startswith(str(BASE_DIR.resolve())):
        raise ValueError("采集结果路径必须在项目目录内")
    if not p.exists():
        raise ValueError(
            f"采集结果不存在：{path}\n"
            f"请先在「资产识别 → 读屏扫描 → 伴生工具自动点击」开启采集并等待完成，"
            f"或检查输出文件名是否与采集时一致（默认 data/artifacts_auto.json）")
    data = json.loads(p.read_text(encoding="utf-8"))

    assets: list[dict] = []
    for c in data.get("characters", []):
        assets.append({"type": "角色", "name": c.get("name", ""),
                       "level": c.get("level"), "entity_id": None})
    for w in data.get("weapons", []):
        assets.append({"type": "武器", "name": w.get("name", ""),
                       "level": w.get("level"), "entity_id": None})
    for a in data.get("artifacts", []):
        assets.append({
            "type": "装备",
            "name": a.get("set") or a.get("name") or "",
            "slot": a.get("slot"),
            "main_stat": a.get("main"),
            "main_stat_value": a.get("main_value"),
            "artifact_level": a.get("level"),
            "substats": a.get("substats") or [],
            "entity_id": None,
        })
    for m in data.get("materials", []):
        if isinstance(m, dict):
            assets.append({"type": "材料", "name": m.get("name", ""),
                           "material_qty": m.get("material_qty"), "entity_id": None})
        elif isinstance(m, str) and m.strip():
            assets.append({"type": "材料", "name": m, "material_qty": None,
                           "entity_id": None})
    return {"assets": assets, "unresolved": []}
