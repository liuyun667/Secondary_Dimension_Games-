"""file_collector：从「导出文件（JSON）」导入资产 —— 推荐路径，零翻页。

导出文件可由伴生工具（如 Amenoma 圣遗物导出器、莫娜占卜铺导出）生成，
或用户手工整理。格式（本服务通用格式）：

{
  "characters": [{"name": "胡桃", "level": 90}],
  "weapons":    [{"name": "护摩之杖", "level": 90}],
  "artifacts":  [{"set": "炽烈的炎之魔女", "slot": "花", "level": 20,
                   "main": "生命值", "substats": ["暴击率", "暴击伤害"]}],
  "materials":  ["摩拉 x999999"]
}

对接其他工具的具体字段名 → 写一个「适配函数」转换成本格式（见 adapt_*）。
"""
from __future__ import annotations

import json


def collect(game_row: dict, payload: dict) -> list[str]:
    content = payload.get("content", "")
    if not content:
        raise ValueError("缺少导出文件内容（payload.content）")
    data = json.loads(content) if isinstance(content, str) else content
    data = adapt_common(data)
    return to_lines(data)


def to_lines(data: dict) -> list[str]:
    lines = []
    for c in data.get("characters", []):
        lines.append(f"{c['name']} Lv.{c.get('level', 90)}")
    for w in data.get("weapons", []):
        lines.append(f"{w['name']} Lv.{w.get('level', 90)}")
    for a in data.get("artifacts", []):
        main = a.get("main", "")
        if a.get("main_value") is not None:
            main = f"{main} {a['main_value']}"
        line = f"{a['set']}（{main}）{a.get('slot', '')}".strip("（） ")
        if a.get("level"):
            line += f" +{a['level']}"
        for s in a.get("substats", []):
            if isinstance(s, dict):
                line += f" {s.get('name', '')}+{s.get('value', '')}{'%' if s.get('percent') else ''}"
            else:
                line += f" {s}"
        lines.append(line)
    lines += [m for m in data.get("materials", []) if m]
    return [ln for ln in lines if ln.strip()]


def adapt_common(data: dict) -> dict:
    """兼容常见字段名（Amenona/莫娜等工具字段各异，可在此扩展适配）。"""
    out = {}
    for src, dst in (("characters", "characters"), ("weapons", "weapons"),
                     ("materials", "materials")):
        out[dst] = data.get(src, [])
    arts = data.get("artifacts") or data.get("圣遗物") or []
    out["artifacts"] = []
    for a in arts:
        out["artifacts"].append({
            "set": a.get("set") or a.get("套装") or a.get("name") or "",
            "slot": a.get("slot") or a.get("部位") or "",
            "level": a.get("level") or a.get("等级") or 0,
            "main": a.get("main") or a.get("主词条") or "",
            "main_value": a.get("main_value") or a.get("主词条数值") or 0,
            "substats": a.get("substats") or a.get("副词条") or [],
        })
    return out
