"""冒烟测试：核心链路断言。可独立运行：python tests/test_smoke.py；也可用 pytest。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 独立临时库
os.environ["GYZ_DB_PATH"] = os.path.join(tempfile.gettempdir(), "gyz_test.db")
if os.path.exists(os.environ["GYZ_DB_PATH"]):
    os.remove(os.environ["GYZ_DB_PATH"])

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import database as db  # noqa: E402
from app import engine, pipeline, seed  # noqa: E402


def setup() -> int:
    seed.seed_all()
    return db.query_one("SELECT id FROM game WHERE code='genshin'")["id"]


def test_hungarian_better_or_equal_greedy() -> None:
    profit = [[100, 85, 70], [60, 100, 40], [50, 55, 100]]
    h = engine.hungarian_maximize if hasattr(engine, "hungarian_maximize") else None
    from app.team_alloc import greedy_with_backtrack, hungarian_maximize
    a1 = hungarian_maximize(profit)
    a2 = greedy_with_backtrack(profit)
    s1 = sum(profit[i][a1[i]] for i in range(len(a1)))
    s2 = sum(profit[i][a2[i]] for i in range(len(a2)))
    assert s1 >= s2, f"Hungarian {s1} 应不劣于贪心 {s2}"


def test_analyze_graduate_recommend() -> None:
    gid = setup()
    lines = ["胡桃 Lv.90 ★5", "护摩之杖 Lv.90 ★5",
             "炽烈的炎之魔女（生命值）花 暴击率+7.8% 暴击伤害+14.0%",
             "炽烈的炎之魔女（火元素伤害加成）杯",
             "炽烈的炎之魔女（暴击率）头"]
    r = pipeline.analyze_lines(lines, gid, "t1")
    assert any(a["type"] == "角色" and a["name"] == "胡桃" for a in r["assets"])
    assert any(a["type"] == "武器" and a["name"] == "护摩之杖" for a in r["assets"])

    hutao = db.query_one("SELECT * FROM entity WHERE game_id=? AND name='胡桃'", (gid,))
    criteria, _ = engine.load_effective_standard(gid, hutao["id"])
    ev = engine.evaluate(hutao, r["assets"], criteria)
    assert 0 <= ev["score"] <= 100
    assert "weapon" in ev["breakdown"]
    assert ev["breakdown"]["weapon"]["score"] == 100.0  # 护摩满级

    # 关闭套装维度 → 权重再分摊且总分仍 ≤100
    ev2 = engine.evaluate(hutao, r["assets"],
                          engine.merge_standard(criteria, {"artifact_set": "off"}, "custom"))
    assert "artifact_set" not in ev2["breakdown"]
    assert 0 <= ev2["score"] <= 100

    rec = engine.recommend_builds(gid, hutao, r["assets"])
    assert rec["builds"], "应返回至少一套配装"
    assert rec["builds"][0]["hit_rate"] > 0


def test_team_recommend() -> None:
    gid = setup()
    assets = pipeline.analyze_lines(
        ["胡桃 Lv.90", "护摩之杖 Lv.90", "祭礼剑 Lv.80", "和璞鸢 Lv.80"], gid, "t2")["assets"]
    members = [db.query_one("SELECT * FROM entity WHERE game_id=? AND name=?", (gid, n))
               for n in ("胡桃", "行秋", "钟离")]
    team = engine.team_recommend(gid, members, assets, {"胡桃": 1.0, "行秋": 0.8, "钟离": 0.6})
    assert 0 <= team["team_score"] <= 100
    assert len(team["members"]) == 3
    assert len(team["assignment"]) == 3           # 三把武器各归其主
    assert len(set(team["assignment"].values())) == 3  # 无重复分配
    assert len(team["priority"]) == 3


def test_custom_standard_persist() -> None:
    gid = setup()
    hutao = db.query_one("SELECT * FROM entity WHERE game_id=? AND name='胡桃'", (gid,))
    db.execute(
        "INSERT INTO user_standard (user_id, game_id, char_id, tier, overrides, "
        "version, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("u1", gid, hutao["id"], "custom", '{"artifact_set": "off"}', "5.0", db.now_iso()))
    criteria, meta = engine.load_effective_standard(gid, hutao["id"], "u1")
    assert meta["tier"] == "custom"
    assert criteria.get("artifact_set") is None  # 已关闭


def _run_all() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"全部 {len(tests)} 项冒烟测试通过")


if __name__ == "__main__":
    _run_all()
