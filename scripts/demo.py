"""端到端演示：模拟截图 → 识别 → 毕业度（默认 vs 自定义）→ 推荐 → 队伍配置 → 反馈。

零第三方依赖，直接运行：python scripts/demo.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 脚本在 scripts/ 下运行，需把项目根目录加入导入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 演示用独立临时库，避免污染正式数据
os.environ["GYZ_DB_PATH"] = os.path.join(tempfile.gettempdir(), "gyz_demo.db")
if os.path.exists(os.environ["GYZ_DB_PATH"]):
    os.remove(os.environ["GYZ_DB_PATH"])

from app import database as db  # noqa: E402
from app import engine, pipeline, seed  # noqa: E402


def main() -> None:
    seed.seed_all()
    gid = db.query_one("SELECT id FROM game WHERE code='genshin'")["id"]

    print("=" * 64)
    print("二游毕业指导 · 端到端演示（模拟背包截图）")
    print("=" * 64)

    # ── 1. 资产识别（模拟 OCR 文本行）────────────────────
    print("\n[1] 资产识别（模拟截图文本行 → OCR 管线）")
    simulated = [
        "胡桃 Lv.90 ★5",
        "护摩之杖 Lv.90 ★5",
        "祭礼剑 Lv.80 ★4",
        "和璞鸢 Lv.80 ★5",
        "炽烈的炎之魔女（生命值）花 暴击率+7.8% 暴击伤害+14.0%",
        "炽烈的炎之魔女（火元素伤害加成）杯",
        "炽烈的炎之魔女（暴击率）头",
        "绝缘之旗印（攻击力）沙",
        "摩拉 x999999",
    ]
    result = pipeline.analyze_lines(simulated, gid, "demo-1")
    for a in result["assets"]:
        print(f"  ✓ [{a['type']}] {a['name']} Lv.{a['level']} "
              f"槽位={a['slot']} 主词条={a['main_stat']} 副词条={a['substats']}")
    if result["unresolved"]:
        print(f"  ✗ 未解析: {result['unresolved']}")

    assets = result["assets"]
    hutao = db.query_one("SELECT * FROM entity WHERE game_id=? AND name='胡桃'", (gid,))

    # ── 2. 毕业度评估（系统默认标准）────────────────────────
    print("\n[2] 毕业度评估（系统默认标准）")
    criteria, _ = engine.load_effective_standard(gid, hutao["id"])
    ev = engine.evaluate(hutao, assets, criteria)
    print(f"  胡桃 毕业度 = {ev['score']}")
    for k, v in ev["breakdown"].items():
        print(f"    {k}: {v['score']} (权重 {v['weight']})")
    for g in ev["gaps"]:
        print(f"    - {g}")

    # ── 3. 自定义标准（放宽「沙位主词条」要求 → 毕业度应上升）──
    print("\n[3] 自定义标准（放宽沙位主词条：接受攻击力）")
    custom = engine.merge_standard(
        criteria, {"main_stats": {"沙": "攻击力", "杯": "火元素伤害加成", "头": "暴击率"}},
        "custom")
    ev2 = engine.evaluate(hutao, assets, custom)
    print(f"  胡桃 毕业度 = {ev['score']} → {ev2['score']}  （按我的标准重新评估）")
    print(f"  main_stats: {ev['breakdown']['main_stats']['score']} → {ev2['breakdown']['main_stats']['score']}")

    # ── 4. 配装推荐 ─────────────────────────────────────
    print("\n[4] 配装推荐（Top-3，含 LLM/模板解释）")
    rec = engine.recommend_builds(gid, hutao, assets, user_id="user-1")
    for b in rec["builds"]:
        print(f"  #{b['hit_rate']:>5}% 武器={b['weapons']} 套装={b['sets']}")
        for g in b["gaps"]:
            print(f"       - {g}")
    print(f"  解释: {rec['explanation']}")

    # ── 5. 队伍整体配置（Hungarian 全局分配）───────────────
    print("\n[5] 队伍整体配置（胡桃蒸发队：胡桃/行秋/钟离）")
    members = [db.query_one("SELECT * FROM entity WHERE game_id=? AND name=?", (gid, n))
               for n in ("胡桃", "行秋", "钟离")]
    team = engine.team_recommend(
        gid, members, assets,
        weights={"胡桃": 1.0, "行秋": 0.8, "钟离": 0.6}, session_id="demo-1")
    print(f"  队伍毕业度 = {team['team_score']}")
    for m in team["members"]:
        print(f"    {m['char']}: {m['score']}  (档位 {m['standard_tier']})")
    print(f"  武器分配: {team['assignment']}  {team['assign_detail']}")
    print(f"  培养优先级: {' → '.join(team['priority'])}")
    print(f"  解释: {team['explanation']}")

    # ── 6. 反馈闭环 ─────────────────────────────────────
    print("\n[6] 反馈闭环（记录采纳，回流训练信号）")
    db.execute(
        "INSERT INTO user_feedback (session_id, target_type, target_id, action, "
        "correction, created_at) VALUES (?,?,?,?,?,?)",
        ("demo-1", "recommend", rec["builds"][0]["build_id"], "采纳", None, db.now_iso()))
    print("  ✓ 已记录采纳反馈（回流缓冲池，攒够阈值触发增量训练）")

    print("\n" + "=" * 64)
    print("演示完成 ✓（数据落在临时库，正式运行用 Web 服务）")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
