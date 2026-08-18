"""测试数据生成器（v2）：点击时实时生成大规模真实向数据。

规模：66 角色（5星≥36、等级≥70）｜ 150 武器（5星≥50、等级≥70）｜
1000 圣遗物（不同部位×套装、等级≥16）｜ 400 材料（≥200 种升级相关，含数量+来源）。
时间戳 = 生成时刻（db.now_iso）。
数据来源：角色/武器取知识库（entity + kb_weapons，真实名），材料取 kb_materials（真实名）。
"""
from __future__ import annotations

import json
import random

from . import database as db
from .kb_materials import UPGRADE_CATS, materials_flat
from .kb_weapons import WEAPONS_GENSHIN

random.seed()   # 每次点击重新播种 → 每次生成不同数据

MAIN_STAT_BY_SLOT = {
    "花": ["生命值"],
    "羽": ["攻击力"],
    "沙": ["攻击力", "生命值", "防御力", "元素精通", "元素充能效率"],
    "杯": ["火元素伤害加成", "水元素伤害加成", "冰元素伤害加成", "雷元素伤害加成",
           "风元素伤害加成", "岩元素伤害加成", "草元素伤害加成", "物理伤害加成",
           "攻击力", "生命值"],
    "头": ["暴击率", "暴击伤害", "治疗加成", "攻击力", "生命值", "元素精通"],
}
SUBSTAT_POOL = [
    ("暴击率", 3.3), ("暴击伤害", 6.6), ("攻击力", 4.1), ("攻击力", 16.5),
    ("防御力", 5.1), ("防御力", 19.7), ("生命值", 4.1), ("生命值", 209),
    ("元素精通", 16.5), ("元素充能效率", 4.5),
]
SLOTS = ["花", "羽", "沙", "杯", "头"]
PERCENT_SUBS = {"暴击率", "暴击伤害", "攻击力", "防御力", "生命值", "元素充能效率"}


def _sets_for_game(game_id: int) -> list[str]:
    rows = db.query("SELECT name FROM entity WHERE game_id=? AND type='装备' ORDER BY id",
                    (game_id,))
    return [r["name"] for r in rows]


def generate_assets(game_id: int = 1) -> list[dict]:
    """实时生成测试资产（四类分开格式）。"""
    assets: list[dict] = []
    chars = db.query(
        "SELECT id, name, rarity FROM entity WHERE game_id=? AND type='角色' "
        "ORDER BY rarity DESC, id", (game_id,))
    five = [c for c in chars if c["rarity"] == 5]
    rest = [c for c in chars if c["rarity"] != 5]
    picks = five[:36] + (five[36:] + rest)[:30]   # 36 个 5星 + 30 个其余 → 66
    # ── 角色 66（5星≥36，等级 70~90）──
    for c in picks:
        assets.append({
            "type": "角色", "entity_id": c["id"], "name": c["name"], "rarity": c["rarity"],
            "level": random.randint(70, 90),
            "constellation": random.randint(0, 6),
            "talents": [random.randint(6, 10) for _ in range(3)],
            "conf": 0.99,
        })
    # ── 武器 150（5星≥50，等级 70~90，精炼/基础攻击/主词条/被动）──
    for wname, rarity, wtype, base_atk, mstat, mval, passive in WEAPONS_GENSHIN:
        ent = db.query_one(
            "SELECT id FROM entity WHERE game_id=? AND type='武器' AND name=?", (game_id, wname))
        if not ent:
            continue
        assets.append({
            "type": "武器", "entity_id": ent["id"], "name": wname, "rarity": rarity,
            "level": random.randint(70, 90),
            "weapon_type": wtype, "refinement": random.randint(1, 5),
            "base_atk": base_atk, "main_stat": mstat,
            "main_stat_value": mval, "passive": passive, "conf": 0.99,
        })
    # ── 圣遗物 1000（不同套装×部位，等级 16~20，主/副属性）──
    sets = _sets_for_game(game_id) or ["炽烈的炎之魔女"]
    for i in range(1000):
        sset = sets[i % len(sets)]
        slot = SLOTS[(i // len(sets)) % len(SLOTS)]
        main = random.choice(MAIN_STAT_BY_SLOT[slot])
        main_val = round(random.uniform(3.0, 60.0) + (i % 10) * 0.7, 1)
        subs = random.sample(SUBSTAT_POOL, random.randint(3, 4))
        substats = [{"name": s[0], "value": round(s[1] + random.uniform(0, 2), 1),
                     "percent": s[0] in PERCENT_SUBS} for s in subs]
        assets.append({
            "type": "装备", "entity_id": None, "set": sset, "slot": slot, "name": sset,
            "level": random.randint(16, 20), "rarity": 5,
            "main_stat": main, "main_stat_value": main_val,
            "substats": substats, "conf": 0.92,
        })
    # ── 材料 400（名称/数量/来源；升级相关 ≥200 种）──
    for mname, cat, source in materials_flat():
        qty = random.randint(5, 999999)
        assets.append({"type": "材料", "entity_id": None, "name": mname,
                       "material_qty": qty, "source": source,
                       "upgrade": cat in UPGRADE_CATS, "conf": 1.0})
    return assets


def generate_test_account(session: str = "test_demo", game_id: int = 1) -> int:
    """生成并写入测试账户（覆盖旧数据），返回资产数。"""
    assets = generate_assets(game_id)
    db.execute("DELETE FROM user_asset WHERE session_id=? AND game_id=?",
               (session, game_id))
    for a in assets:
        db.execute(
            "INSERT INTO user_asset (session_id, game_id, type, entity_id, level, rarity, "
            "slot, stats, raw_text, conf, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (session, game_id, a.get("type"), a.get("entity_id"),
             a.get("level"), a.get("rarity"), a.get("slot"),
             json.dumps({"main_stat": a.get("main_stat"),
                         "main_stat_value": a.get("main_stat_value"),
                         "artifact_level": a.get("artifact_level"),
                         "substats": a.get("substats") or [],
                         "constellation": a.get("constellation"),
                         "talents": a.get("talents"),
                         "material_qty": a.get("material_qty"),
                         "set": a.get("set"),
                         "weapon_type": a.get("weapon_type"),
                         "refinement": a.get("refinement"),
                         "base_atk": a.get("base_atk"),
                         "passive": a.get("passive"),
                         "source": a.get("source"),
                         "upgrade": a.get("upgrade")}, ensure_ascii=False),
             a.get("raw_text") or a.get("name"), a.get("conf"), db.now_iso()))
    return len(assets)


def counts(assets: list[dict]) -> dict:
    from collections import Counter
    kinds = Counter(a["type"] for a in assets)
    five_w = sum(1 for a in assets if a["type"] == "武器" and a["rarity"] == 5)
    five_c = sum(1 for a in assets if a["type"] == "角色" and a["rarity"] == 5)
    return {"total": len(assets), "kinds": dict(kinds),
            "武器5星": five_w, "角色5星": five_c}
