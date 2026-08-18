"""20 卡压力测试（v1.4 RapidOCR 后回归）：auto_export 解析 → 导入 → 识别 → 毕业度。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import importlib.util

ROOT = r"D:\software\deepseeek_harness\二游毕业指导"
sys.path.insert(0, ROOT)
os.environ["GYZ_DB_PATH"] = os.path.join(tempfile.gettempdir(), "gyz_stress20.db")
if os.path.exists(os.environ["GYZ_DB_PATH"]):
    os.remove(os.environ["GYZ_DB_PATH"])

# 1) auto_export 离线解析 20 卡
spec = importlib.util.spec_from_file_location("ae", os.path.join(ROOT, "tools", "auto_export.py"))
ae = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ae)
out = os.path.join(tempfile.gettempdir(), "art20.json")
t0 = time.time()
ae.from_text_file(os.path.join(ROOT, "tools", "sample_ocr_20.txt"), out)
dt = (time.time() - t0) * 1000
data = json.load(open(out, encoding="utf-8"))
cards = data["artifacts"]

# 2) 字段完整性校验
ok, problems = 0, []
for i, c in enumerate(cards):
    issues = []
    if not c.get("set"): issues.append("缺套装")
    if not c.get("slot"): issues.append("缺部位")
    if not c.get("main"): issues.append("缺主词条")
    if c.get("level") != 20: issues.append(f'强化异常:{c.get("level")}')
    if not c.get("substats"): issues.append("缺副词条")
    if issues:
        problems.append(f"卡{i+1}: {issues}")
    else:
        ok += 1
print(f"解析 {len(cards)} 张卡, 耗时 {dt:.0f}ms, 字段完整 {ok}/{len(cards)}")
for p in problems[:5]:
    print("  ✗", p)

# 3) 导入 → 识别 → 毕业度
from app import database as db, seed, collectors, engine  # noqa: E402

seed.seed_all()
r = collectors.run_collector(1, "file", {"content": json.dumps(data, ensure_ascii=False)})
assets = r["assets"]
print(f"导入识别: {len(assets)} 项, 未识别 {len(r['unresolved'])} 项")
eq = [a for a in assets if a["type"] == "装备"]
print(f"装备: {len(eq)} 件, 带数值副词条: {sum(1 for a in eq if a['substats'])}/{len(eq)}")
hutao = db.query_one("SELECT * FROM entity WHERE game_id=1 AND name='胡桃'")
criteria, _ = engine.load_effective_standard(1, hutao["id"])
ev = engine.evaluate(hutao, assets, criteria)
print(f"胡桃毕业度: {ev['score']} 分")
print("压力测试:", "通过 ✓" if ok == len(cards) and len(r["unresolved"]) == 0 else "存在异常 ✗")
