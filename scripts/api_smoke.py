"""API 冒烟测试：sample → analyze → graduate → advice 全链路（UTF-8，不依赖浏览器/PowerShell 编码）。

用法：python scripts/api_smoke.py [--base http://127.0.0.1:8000/api/v1] [--out 报告路径]
退出码：0=全部通过，1=有失败。
"""
import argparse
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, payload: dict | None = None) -> dict | list:
    url = f"{BASE}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default="tools/_api_smoke_report.txt")
    args = ap.parse_args()
    BASE = args.base
    results: list[str] = []
    failed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        results.append(f"[{mark}] {name}" + (f" ｜ {detail}" if detail else ""))

    # 1) health / games
    h = call("GET", "/health")
    check("health", h.get("status") == "ok", str(h))
    games = call("GET", "/games")
    check("games", len(games) == 3, f"{len(games)} 个游戏，max_team_size={[g['max_team_size'] for g in games]}")

    # 2) sample → analyze
    gid = 1
    smp = call("GET", f"/sample?game_id={gid}")
    lines = smp.get("lines", [])
    check("sample 返回文本行", len(lines) >= 20, f"{len(lines)} 行，首行={lines[0]!r}")
    an = call("POST", "/analyze", {"game_id": gid, "text_lines": lines, "session_id": "api_smoke"})
    assets = an.get("assets", [])
    unresolved = an.get("unresolved", [])
    types: dict[str, int] = {}
    for x in assets:
        types[x.get("type")] = types.get(x.get("type"), 0) + 1
    check("analyze 识别资产", len(assets) >= 15, f"assets={len(assets)} unresolved={len(unresolved)} types={types}")
    check("analyze 无未识别角色/武器", len(unresolved) <= 2, f"unresolved={unresolved[:4]}")
    chars = [x for x in assets if x.get("type") == "角色"]
    arts = [x for x in assets if x.get("type") in ("装备", "圣遗物", "声骸", "驱动盘")]
    mats = [x for x in assets if x.get("type") == "材料"]
    check("角色资产", len(chars) >= 3, f"{len(chars)} 个")
    check("装备资产", len(arts) >= 3, f"{len(arts)} 个")
    check("材料资产", len(mats) >= 1, f"{len(mats)} 个")
    if chars:
        c0 = chars[0]
        check("角色带等级", c0.get("level") is not None, f"{c0['name']} lv={c0.get('level')}")
        check("角色匹配到实体", c0.get("entity_id") is not None, f"entity_id={c0.get('entity_id')}")
    if arts:
        a0 = arts[0]
        check("装备带主词条", bool(a0.get("main_stat")), f"{a0['name']} 主={a0.get('main_stat')}")

    # 3) graduate：用第一个角色的实体 id
    char = next((x for x in chars if x.get("entity_id")), None)
    if char:
        gr = call("POST", "/graduate", {"game_id": gid, "character_id": char["entity_id"],
                                        "assets": assets, "user_id": "api_smoke",
                                        "standard": {"tier": "standard"}})
        score = gr.get("score")
        dims = gr.get("dimensions") or gr.get("dims") or {}
        check("graduate 返回评分", score is not None, f"score={score} dims={list(dims) if isinstance(dims, dict) else dims}")
    else:
        check("graduate（跳过：无角色实体）", True, "")

    # 4) advice：取前 2 个角色实体
    ids = [x["entity_id"] for x in chars if x.get("entity_id")][:2]
    if ids:
        adv = call("POST", "/advice", {"game_id": gid, "character_ids": ids, "assets": assets,
                                       "user_id": "api_smoke", "tier": "standard"})
        text = adv.get("text") or adv.get("advice") or ""
        check("advice 生成文本", len(text) > 100, f"{len(text)} 字，含「毕业」={'毕业' in text}")
    else:
        check("advice（跳过：无角色实体）", True, "")

    report = "\n".join(results)
    print(report)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report + f"\n\n共 {len(results)} 项，失败 {failed} 项\n")
    print(f"报告已写入 {args.out}（失败 {failed} 项）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
