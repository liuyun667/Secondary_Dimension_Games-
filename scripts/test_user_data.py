"""用户数据全链路测试：用「完整背包」示例数据（每游戏约 10 角色）跑通全流程。

覆盖：资产识别 → 资产保存/删除 → 毕业度评估 → 批量配装 → 队伍配置。
运行：python scripts/test_user_data.py （退出码 0=全部通过）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["GYZ_DB_PATH"] = os.path.join(tempfile.gettempdir(), "gyz_user_test.db")
if os.path.exists(os.environ["GYZ_DB_PATH"]):
    os.remove(os.environ["GYZ_DB_PATH"])

from app import database as db, engine, pipeline, sample_data, seed  # noqa: E402

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if ok:
        PASS_COUNT += 1
        print(f"  ✅ {name} {detail}")
    else:
        FAIL_COUNT += 1
        print(f"  ❌ {name} {detail}")


def main() -> int:
    seed.seed_all()
    gid_of = {g["name"]: g["id"] for g in db.query("SELECT id, name FROM game")}

    for gname in sample_data.SAMPLE:
        gid = gid_of[gname]
        session = f"用户-{gname}"
        lines = sample_data.lines_for(gname)
        print(f"\n{'=' * 60}\n【游戏】{gname}（id={gid}）完整背包 {len(lines)} 行\n{'=' * 60}")

        # 1. 资产识别
        r = pipeline.analyze_lines(lines, gid, session)
        assets = r["assets"]
        types: dict[str, int] = {}
        for a in assets:
            types[a["type"]] = types.get(a["type"], 0) + 1
        check("资产识别", len(assets) > 0,
              f"识别 {len(assets)} 项，类型 {types}，未识别 {len(r['unresolved'])} 项")

        # 2. 资产保存（先删后插，与真实接口语义一致）
        db.execute("DELETE FROM user_asset WHERE session_id=? AND game_id=?",
                   (session, gid))
        for a in assets:
            db.execute(
                "INSERT INTO user_asset (session_id, game_id, entity_id, level, rarity, "
                "slot, stats, raw_text, conf, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (session, gid, a.get("entity_id"), a.get("level"), a.get("rarity"),
                 a.get("slot"),
                 json.dumps({"main_stat": a.get("main_stat"),
                             "substats": a.get("substats") or []}, ensure_ascii=False),
                 a.get("raw_text") or a.get("name"), a.get("conf"), db.now_iso()))
        cnt = db.query_one("SELECT COUNT(*) AS c FROM user_asset WHERE session_id=?",
                           (session,))["c"]
        check("资产保存", cnt == len(assets), f"写入 {cnt} 条")

        # 3. 资产删除
        db.execute("DELETE FROM user_asset WHERE session_id=?", (session,))
        cnt = db.query_one("SELECT COUNT(*) AS c FROM user_asset WHERE session_id=?",
                           (session,))["c"]
        check("资产删除", cnt == 0, "已清空")

        # 4. 毕业度评估（前 2 个角色）
        roles = [a for a in assets if a["type"] == "角色"][:2]
        for role in roles:
            char = db.query_one("SELECT * FROM entity WHERE id=?", (role["entity_id"],))
            criteria, _ = engine.load_effective_standard(gid, char["id"])
            ev = engine.evaluate(char, assets, criteria)
            check(f"毕业度[{char['name']}]", 0 <= ev["score"] <= 100,
                  f"{ev['score']} 分，差距 {len(ev['gaps'])} 项")

        # 5. 批量配装（2 人）
        ids = [role["entity_id"] for role in roles]
        recs = engine.recommend_batch(gid, ids, assets)
        check("批量配装", len(recs) == len(ids), f"生成 {len(recs)} 人方案")
        for rec in recs:
            print(f"      {rec['character']}: Top 命中率 {rec['builds'][0]['hit_rate']}%")

        # 6. 队伍配置（2 人）
        members = [db.query_one("SELECT * FROM entity WHERE id=?", (i,)) for i in ids]
        team = engine.team_recommend(gid, members, assets, None, session)
        check("队伍配置", 0 <= team["team_score"] <= 100,
              f"队伍毕业度 {team['team_score']}，武器分配 {len(team['assignment'])} 件，"
              f"培养顺序 {team['priority']}")

    print(f"\n{'=' * 60}\n汇总：通过 {PASS_COUNT} 项，失败 {FAIL_COUNT} 项\n{'=' * 60}")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
