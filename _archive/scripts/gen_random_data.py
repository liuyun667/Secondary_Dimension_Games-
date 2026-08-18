"""随机用户数据生成器：随机生成 N 个账户，跑识别 + 毕业度抽检，输出分布统计。

用法：
    python scripts/gen_random_data.py --accounts 5 --games 1,2,3 --seed 42
    python scripts/gen_random_data.py -a 20 -g 1          # 20 个原神账户
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["GYZ_DB_PATH"] = os.path.join(tempfile.gettempdir(), "gyz_random_test.db")
if os.path.exists(os.environ["GYZ_DB_PATH"]):
    os.remove(os.environ["GYZ_DB_PATH"])

from app import database as db, engine, pipeline, sample_data, seed  # noqa: E402


def gen_lines(gname: str, rng: random.Random) -> list[str]:
    """随机生成一个账户的背包文本行（角色数/等级/装备数量随机）。"""
    s = sample_data.SAMPLE[gname]
    lines = []
    chars = rng.sample(s["characters"], rng.randint(2, len(s["characters"])))
    for name, _ in chars:
        lines.append(f"{name} Lv.{rng.choice([60, 70, 80, 85, 90])}")
    for name, _ in rng.sample(s["weapons"], rng.randint(1, len(s["weapons"]))):
        lines.append(f"{name} Lv.{rng.choice([70, 80, 90])}")
    for setname, stat, slot in rng.sample(s["equipment"],
                                          rng.randint(0, len(s["equipment"]))):
        lines.append(f"{setname}（{stat}）{slot}")
    for mat in rng.sample(s["materials"], rng.randint(1, len(s["materials"]))):
        lines.append(f"{mat.split(' x')[0]} x{rng.randint(100, 999999)}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", "-a", type=int, default=5, help="生成账户数")
    ap.add_argument("--games", "-g", default="1,2,3", help="游戏 id 列表，逗号分隔")
    ap.add_argument("--seed", type=int, default=42, help="随机种子")
    args = ap.parse_args()

    seed.seed_all()
    wanted = [int(x) for x in args.games.split(",") if x.strip()]
    games = [g for g in db.query("SELECT id, name FROM game") if g["id"] in wanted]
    if not games:
        print("没有可用的游戏 id，请检查 --games")
        return 1
    rng = random.Random(args.seed)

    stats = {"accounts": 0, "lines": 0, "assets": 0, "unresolved": 0, "scores": []}
    t0 = time.time()
    for acc in range(1, args.accounts + 1):
        g = rng.choice(games)
        gname = g["name"]
        lines = gen_lines(gname, rng)
        r = pipeline.analyze_lines(lines, g["id"], f"随机账户{acc}")
        stats["accounts"] += 1
        stats["lines"] += len(lines)
        stats["assets"] += len(r["assets"])
        stats["unresolved"] += len(r["unresolved"])

        score = None
        roles = [a for a in r["assets"] if a["type"] == "角色"]
        if roles:
            role = rng.choice(roles)
            char = db.query_one("SELECT * FROM entity WHERE id=?", (role["entity_id"],))
            criteria, _ = engine.load_effective_standard(g["id"], char["id"])
            score = engine.evaluate(char, r["assets"], criteria)["score"]
            stats["scores"].append(score)
        print(f"账户{acc:>2} [{gname}] 文本{len(lines):>2} 行 → 识别{len(r['assets']):>2} 项"
              f"（未识别 {len(r['unresolved'])}）｜ 抽检毕业度 "
              f"{score if score is not None else '—'}")

    elapsed = time.time() - t0

    def pct(x: int, y: int) -> str:
        return f"{x / y * 100:.1f}%" if y else "—"

    print("\n" + "=" * 60)
    print("汇总")
    print(f"账户数       : {stats['accounts']}")
    print(f"文本总行数   : {stats['lines']}")
    print(f"识别资产数   : {stats['assets']}")
    print(f"未识别数     : {stats['unresolved']}（占文本 {pct(stats['unresolved'], stats['lines'])}）")
    if stats["scores"]:
        avg = sum(stats["scores"]) / len(stats["scores"])
        print(f"毕业度分布   : 平均 {avg:.1f} ｜ 最低 {min(stats['scores'])} ｜ 最高 {max(stats['scores'])}")
    print(f"总耗时       : {elapsed:.2f}s（每账户平均 {elapsed / max(args.accounts, 1):.2f}s）")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
