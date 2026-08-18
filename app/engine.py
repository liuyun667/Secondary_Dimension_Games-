"""推荐引擎：毕业标准合并 → 毕业度评估 → 配装推荐 → 队伍分配 → LLM 解释。

对应文档 §3.5 / §3.7.1 / §3.7.2。默认规则实现零依赖；RF/LLM 按需启用。
"""
from __future__ import annotations

import json
import urllib.request

from . import config, database as db
from .constants import DIM_WEIGHTS, SUBSTAT_ROLL_MIN
from .team_alloc import greedy_with_backtrack, hungarian_maximize

# 快速模板（§3.7.1）：休闲 / 标准 / 极限 —— 档位决定整体目标（等级/武器/副词条）
TEMPLATES = {
    "casual": {"level": 80,
               "weapon": {"min_level": 80},
               "substat_targets": {"暴击率": 45, "暴击伤害": 150}},
    "standard": {"level": 90},
    "extreme": {"level": 90,
                "weapon": {"min_level": 90},
                "substat_targets": {"暴击率": 70, "暴击伤害": 240}},
}

TIER_ALIAS = {"casual": "休闲", "standard": "标准", "extreme": "极限", "custom": "自定义"}


# ── 1. 毕业标准合并（默认 + 模板 + 自定义覆盖）───────────
def _apply(eff: dict, patch: dict | None) -> dict:
    """overrides 语义（组D1）：
    - 值 == "off" → 维度关闭（None）
    - dict → 深度合并（嵌套字段覆盖）
    - 键以 "_append" 结尾 → 追加到同名前缀的列表（如 weapon.best_append）
    - 其他 → 替换
    """
    if not patch:
        return eff
    for k, v in patch.items():
        if k.endswith("_append"):
            base = k[:-len("_append")]
            cur = eff.get(base)
            items = v if isinstance(v, list) else [v]
            eff[base] = (cur + items) if isinstance(cur, list) else items
            continue
        if v == "off":
            eff[k] = None
        elif isinstance(v, dict):
            cur = eff.get(k)
            if isinstance(cur, dict):
                eff[k] = _apply(json.loads(json.dumps(cur)), v)   # 递归：嵌套 dict 也支持 _append/off
            else:
                eff[k] = json.loads(json.dumps(v))
        else:
            eff[k] = v
    return eff


def merge_standard(criteria: dict, overrides: dict | None,
                   tier: str = "standard") -> dict:
    """生效标准 = 默认(社区) + 全局模板(tier) + 角色专属档位(criteria.tiers[tier]) + 自定义(overrides)。

    优先级：角色专属档位 > 全局模板 > 默认标准（专属档位可覆盖全局模板的等级/词条目标）。
    criteria.tiers 形如 {"casual": {...}, "standard": {...}, "extreme": {...}}。
    """
    tiers_cfg = (criteria or {}).get("tiers") or {}
    eff = json.loads(json.dumps(criteria or {}))
    eff.pop("tiers", None)                    # 配置字段不进入生效标准
    eff = _apply(eff, TEMPLATES.get(tier, {}))
    if tiers_cfg.get(tier):
        eff = _apply(eff, tiers_cfg[tier])
    eff = _apply(eff, overrides or {})
    return eff


def load_effective_standard(game_id: int, char_id: int,
                            user_id: str | None = None) -> tuple[dict, dict]:
    """读取该角色毕业标准并合并用户自定义（若存在）。返回 (生效标准, 元信息)。"""
    row = db.query_one(
        "SELECT * FROM kb_graduation WHERE game_id=? AND char_id=? AND status='生效' "
        "ORDER BY version DESC LIMIT 1", (game_id, char_id))
    criteria = json.loads(row["criteria"]) if row else {}
    meta = {"tier": "standard", "overrides": {}}
    if user_id:
        us = db.query_one(
            "SELECT * FROM user_standard WHERE user_id=? AND game_id=? AND char_id=? "
            "ORDER BY updated_at DESC LIMIT 1", (user_id, game_id, char_id))
        if us:
            meta = {"tier": us["tier"], "overrides": json.loads(us["overrides"] or "{}")}
    return merge_standard(criteria, meta["overrides"], meta["tier"]), meta


def redistribute_weights(active_dims: list[str]) -> dict[str, float]:
    """关闭维度后权重按比例分摊（保证总分仍 0~100，§4.3）。"""
    w = {k: DIM_WEIGHTS[k] for k in active_dims if k in DIM_WEIGHTS}
    total = sum(w.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in w.items()}


# ── 2. 毕业度评估 ─────────────────────────────────────
def _set_of(asset: dict) -> str:
    """取装备的套装名：优先独立 set 字段（四类分开保存后），否则从 name 解析。"""
    s = asset.get("set")
    if s:
        return str(s)
    return (asset["name"] or "").split("·")[0]


def aggregate_substats(artifacts: list[dict]) -> dict[str, dict]:
    """汇总副词条：{词条名: {"count": 出现件数, "value": 数值累加}}。

    支持两种来源：旧格式（名字列表）与新格式（{"name","value","percent"}）。
    """
    agg: dict[str, dict] = {}
    for a in artifacts:
        for s in a.get("substats") or []:
            name = s["name"] if isinstance(s, dict) else s
            value = float(s.get("value") or 0) if isinstance(s, dict) else 0.0
            e = agg.setdefault(name, {"count": 0, "value": 0.0})
            e["count"] += 1
            e["value"] += value
    return agg


def substat_status(assets: list[dict], criteria: dict) -> list[dict]:
    """按角色毕业标准逐词条判定副词条达标状态（组B1：单件达标，废除跨装备累加）。

    达标滚 = 单件副词条数值 ≥ SUBSTAT_ROLL_MIN 该词条下限。
    返回：[{name, target, count(有该词条的件数), ok_count(达标件数), status}]
    """
    st = criteria.get("substat_targets") or {}
    arts = [a for a in assets if a["type"] == "装备"]
    out = []
    for k, t in st.items():
        rolls = []
        for a in arts:
            for s in a.get("substats") or []:
                if isinstance(s, dict) and s.get("name") == k and s.get("value") is not None:
                    rolls.append(float(s["value"]))
        ok = [v for v in rolls if v >= SUBSTAT_ROLL_MIN.get(k, 0)]
        if not rolls:
            status = "未出现"
        elif ok:
            status = "达标"
        else:
            status = "未达标"
        out.append({"name": k, "target": t, "count": len(rolls),
                    "ok_count": len(ok), "status": status})
    return out


def evaluate(character: dict, assets: list[dict], criteria: dict) -> dict:
    """角色毕业度：分项完成度 → 加权总分 + 差距清单。

    规则：无资产数据的维度不参与（等价于"关闭"），权重再分摊。
    """
    dims: dict[str, float] = {}
    gaps: list[str] = []

    # level
    target = criteria.get("level", 90)
    role = next((a for a in assets
                 if a["type"] == "角色" and a["name"] == character["name"]), None)
    if role and role.get("level"):
        dims["level"] = min(1.0, role["level"] / target)
    elif role:
        dims["level"] = 0.0
        gaps.append(f"角色等级不足（目标 Lv.{target}）")

    # weapon
    w = criteria.get("weapon")
    if w:
        best = w.get("best") or []
        min_lv = w.get("min_level", 90)
        weps = [a for a in assets if a["type"] == "武器"]
        own_best = next((a for a in weps if a["name"] in best), None)
        if own_best:
            lv = own_best.get("level") or 0
            dims["weapon"] = min(1.0, lv / min_lv)
            if lv < min_lv:
                gaps.append(f"武器 {own_best['name']} 未满级（{lv}/{min_lv}）")
        elif weps:
            dims["weapon"] = 0.4
            gaps.append(f"缺少最佳武器（推荐：{'/'.join(best)}），当前用替代")
        else:
            dims["weapon"] = 0.0
            gaps.append(f"缺少武器（推荐：{'/'.join(best)}）")

    # artifact_set
    sets = criteria.get("artifact_set") or []
    arts = [a for a in assets if a["type"] == "装备"]
    own_sets = {_set_of(a) for a in arts}
    if sets:
        hit = next((s for s in sets if s in own_sets), None)
        dims["artifact_set"] = 1.0 if hit else 0.0
        if not hit:
            gaps.append(f"缺少套装（{'/'.join(sets)}）")

    # main_stats（组A3：只认该角色毕业标准要求的套装，避免别的套装混入）
    ms = criteria.get("main_stats") or {}
    if ms:
        sets_req = criteria.get("artifact_set") or []
        arts_set = [a for a in arts if (not sets_req) or (_set_of(a) in sets_req)]
        hits = sum(1 for slot, stat in ms.items()
                   if any(a.get("slot") == slot and a.get("main_stat") == stat
                          for a in arts_set))
        dims["main_stats"] = hits / len(ms)
        for slot, stat in ms.items():
            if not any(a.get("slot") == slot and a.get("main_stat") == stat
                       for a in arts_set):
                gaps.append(f"{slot}位主词条不符（应为 {stat}）")

    # substats（组B1：单件达标滚判定，不跨装备累加）
    st = criteria.get("substat_targets") or {}
    substat_detail = substat_status(assets, criteria)
    if st:
        ratios = []
        for d in substat_detail:
            if d["status"] == "达标":
                ratios.append(1.0)
            elif d["status"] == "未达标":
                ratios.append(0.5)   # 有该词条但无达标滚 → 半价
            else:  # 未出现
                ratios.append(0.0)
        dims["substats"] = sum(ratios) / len(ratios) if ratios else 0.0
        for d in substat_detail:
            if d["status"] == "未出现":
                gaps.append(f"副词条 {d['name']} 未出现（面板目标 {d['target']}）")
            elif d["status"] == "未达标":
                gaps.append(f"副词条 {d['name']} 无达标滚（{d['count']} 件均低于达标线）")

    # talent：按毕业标准中的技能等级目标逐项评估（普通攻击/元素战绩/元素爆发，默认 9/9/9）
    # role.talents 顺序 = (普攻, 战绩, 爆发)，如「天赋 9 10 10」→ [9, 10, 10]
    if role and role.get("talents"):
        tg = criteria.get("talents") or {"normal": 9, "skill": 9, "burst": 9}
        order = ("normal", "skill", "burst")
        labels = {"normal": "普通攻击", "skill": "元素战绩", "burst": "元素爆发"}
        lv = role["talents"]
        rows = [(labels[order[i]], lv[i], int(tg.get(order[i], 9)))
                for i in range(min(len(lv), len(order)))]
        dims["talent"] = sum(min(1.0, cur / tgt) for _, cur, tgt in rows) / len(rows)
        for label, cur, tgt in rows:
            if cur < tgt:
                gaps.append(f"天赋·{label}不足（当前 {cur}/目标 {tgt}）")
    weights = redistribute_weights(list(dims.keys()))
    score = sum(weights[k] * dims[k] for k in dims) if weights else 0.0
    return {
        "score": round(score * 100, 1),
        "breakdown": {k: {"score": round(dims[k] * 100, 1),
                          "weight": round(weights[k], 3)} for k in dims},
        "gaps": gaps,
        "substat_detail": substat_detail,
    }


# ── 3. 配装推荐 ──────────────────────────────────────
def _weapon_score(member_name: str, weapon: dict, builds: list[dict]) -> float:
    """规则评分：命中该成员最佳武器 100 / 次选 85 / 替代 70 / 其余按稀有度。
    真实实现：RF 对结构化特征打分（GYZ_USE_RF=1，见 _rf_score）。"""
    if config.USE_RF:
        return _rf_score(member_name, weapon)
    best = builds[0]["weapon_names"] if builds else []
    if weapon["name"] in best:
        idx = best.index(weapon["name"])
        return {0: 100.0, 1: 85.0}.get(idx, 70.0)
    return 30.0 + 10.0 * (weapon.get("rarity") or 3)


def _rf_score(member_name: str, weapon: dict) -> float:  # pragma: no cover - 可选
    """可选：sklearn 随机森林对 (稀有度, 主词条匹配, 副词条数值) 等特征打分。"""
    import numpy as np  # type: ignore
    from sklearn.ensemble import RandomForestRegressor  # type: ignore
    # TODO: 用离线标注数据训练；此处仅为接入骨架
    model = RandomForestRegressor(n_estimators=50, random_state=42)
    X = np.array([[weapon.get("rarity") or 3, 1.0, 0.5]])
    model.fit(X, np.array([80.0]))  # 占位训练
    return float(model.predict(X)[0])


def recommend_builds(game_id: int, character: dict, assets: list[dict],
                     user_id: str | None = None) -> dict:
    """Top-3 配装：知识库检索 → 命中率 → 排序 → LLM 解释。"""
    builds = db.query(
        "SELECT * FROM kb_build WHERE game_id=? AND char_id=? ORDER BY version DESC",
        (game_id, character["id"]))

    def entity_name(eid: int) -> str:
        row = db.query_one("SELECT name FROM entity WHERE id=?", (eid,))
        return row["name"] if row else str(eid)

    # 预解析武器/套装名，供评分与命中率计算
    for b in builds:
        b["weapon_names"] = [entity_name(i) for i in json.loads(b["weapon_ids"] or "[]")]
        b["set_names"] = [entity_name(i) for i in json.loads(b["artifact_ids"] or "[]")]
        b["main_stats"] = json.loads(b["main_stats"] or "{}")

    results = []
    for b in builds:
        weps = [a for a in assets if a["type"] == "武器"]
        arts = [a for a in assets if a["type"] == "装备"]

        weapon_hit = next((a for a in weps if a["name"] in b["weapon_names"]), None)
        weapon_score = 1.0 if weapon_hit else (0.5 if weps else 0.0)

        own_sets = {_set_of(a) for a in arts}
        set_score = 1.0 if any(s in own_sets for s in b["set_names"]) else 0.0

        ms = b["main_stats"]
        arts_set = [a for a in arts if (not b["set_names"]) or (_set_of(a) in b["set_names"])]
        main_hits = sum(1 for slot, stat in ms.items()
                        if any(a.get("slot") == slot and a.get("main_stat") == stat
                               for a in arts_set))
        main_score = main_hits / len(ms) if ms else 1.0

        hit_rate = 0.4 * weapon_score + 0.3 * set_score + 0.3 * main_score
        gaps = []
        if not weapon_hit:
            gaps.append(f"缺最佳武器（推荐 {'/'.join(b['weapon_names'])}）")
        if set_score < 1.0:
            gaps.append(f"缺套装（{'/'.join(b['set_names'])}）")
        for slot, stat in ms.items():
            if not any(a.get("slot") == slot and a.get("main_stat") == stat
                       for a in arts_set):
                gaps.append(f"{slot}位主词条应为 {stat}")

        results.append({
            "build_id": b["id"], "weapons": b["weapon_names"],
            "sets": b["set_names"], "main_stats": ms,
            "hit_rate": round(hit_rate * 100, 1), "gaps": gaps,
        })

    results.sort(key=lambda r: r["hit_rate"], reverse=True)
    top = results[:3]

    eff, meta = load_effective_standard(game_id, character["id"], user_id)
    explanation = llm_explain(character["name"], top, meta)
    return {"character": character["name"], "builds": top,
            "standard": {"tier": meta["tier"],
                         "tier_name": TIER_ALIAS.get(meta["tier"], meta["tier"])},
            "substat_detail": substat_status(assets, eff),
            "explanation": explanation}


# ── 4. 队伍整体配置（§3.7.2）──────────────────────────
def team_recommend(game_id: int, members: list[dict], assets: list[dict],
                   weights: dict[str, float] | None = None,
                   session_id: str = "session-demo") -> dict:
    """全员方案 + 全局武器分配（Hungarian）+ 队伍毕业度 + 培养优先级。"""
    weights = weights or {m["name"]: 1.0 for m in members}
    per_member, member_scores = [], {}

    for m in members:
        criteria, meta = load_effective_standard(game_id, m["id"])
        ev = evaluate(m, assets, criteria)
        member_scores[m["name"]] = ev["score"]
        per_member.append({
            "char": m["name"], "score": ev["score"],
            "gaps": ev["gaps"], "standard_tier": meta["tier"],
        })

    # 全局武器分配：成员 × 用户武器资产 收益矩阵 → Hungarian
    weps = [a for a in assets if a["type"] == "武器"]
    assignment = {}
    assign_detail = None
    if weps:
        builds = {m["name"]: db.query(
            "SELECT * FROM kb_build WHERE game_id=? AND char_id=? ORDER BY version DESC",
            (game_id, m["id"])) for m in members}
        for m in members:
            for b in builds[m["name"]]:
                b["weapon_names"] = [db.query_one("SELECT name FROM entity WHERE id=?",
                                                  (i,))["name"]
                                     for i in json.loads(b["weapon_ids"] or "[]")]
        profit = [[_weapon_score(m["name"], w, builds[m["name"]]) for w in weps]
                  for m in members]
        assign_idx = hungarian_maximize(profit)
        for i, m in enumerate(members):
            if assign_idx[i] != -1:
                assignment[m["name"]] = weps[assign_idx[i]]["name"]
        assign_detail = {
            "method": "hungarian",
            "total_profit": round(sum(profit[i][assign_idx[i]] for i in range(len(members))
                                      if assign_idx[i] != -1), 1),
        }

    total_w = sum(weights.values())
    team_score = (sum(member_scores[n] * weights[n] for n in member_scores) / total_w
                  if total_w else 0.0)
    priority = sorted(members, key=lambda m: weights.get(m["name"], 1.0)
                      * (100 - member_scores[m["name"]]), reverse=True)

    db.execute(
        "INSERT INTO team_graduate (session_id, game_id, member_ids, member_weights, "
        "score, per_member, assignment, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (session_id, game_id,
         json.dumps([m["id"] for m in members], ensure_ascii=False),
         json.dumps(weights, ensure_ascii=False), round(team_score, 1),
         json.dumps(per_member, ensure_ascii=False),
         json.dumps({"assignment": assignment, "detail": assign_detail},
                    ensure_ascii=False),
         db.now_iso()))

    return {
        "team_score": round(team_score, 1),
        "members": per_member,
        "assignment": assignment,
        "assign_detail": assign_detail,
        "priority": [m["name"] for m in priority],
        "explanation": (f"队伍毕业度 {team_score:.1f}，建议按优先级培养："
                        f"{' → '.join(m['name'] for m in priority)}。"
                        f"武器已按全局最优分配（Hungarian）。"),
    }


# ── 5. LLM 解释（可选，urllib 实现）───────────────────
def llm_polish_advice(template: str) -> str:
    """把结构化培养建议改写成自然、专业的文本；无 key / 失败返回原模板。"""
    if not config.DEEPSEEK_API_KEY:
        return template
    try:
        body = json.dumps({
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system",
                 "content": "你是二次元游戏培养顾问。请把用户给出的结构化培养建议改写成自然、专业、"
                            "可直接复制给玩家的中文培养建议：保持所有数据准确（等级/材料/配装/加点），"
                            "分条清晰、语气友好，用「■」分隔不同角色。"},
                {"role": "user", "content": template},
            ],
            "max_tokens": 800,
        }).encode("utf-8")
        req = urllib.request.Request(
            config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
            data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001 - 网络/限流失败降级模板
        return template


def llm_explain(character: str, builds: list[dict], standard_meta: dict) -> str:
    """DeepSeek API 生成推荐理由；无 key / 失败时返回模板文案。"""
    prompt = (f"玩家角色【{character}】的配装推荐（毕业标准档位："
              f"{TIER_ALIAS.get(standard_meta['tier'], standard_meta['tier'])}）：\n"
              + json.dumps(builds, ensure_ascii=False, indent=2)
              + "\n请用 3 句话给出推荐理由与优先培养建议（中文）。")

    if config.DEEPSEEK_API_KEY:
        try:
            body = json.dumps({
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
            }).encode("utf-8")
            req = urllib.request.Request(
                config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except Exception:  # noqa: BLE001 - 网络/限流失败降级模板
            pass

    return (f"推荐优先补齐 {character} 的武器与主词条："
            f"第 1 方案命中率 {builds[0]['hit_rate']}%。"
            + ("主要缺口：" + "；".join(builds[0]["gaps"]) if builds[0]["gaps"]
               else "当前资产已基本满足毕业要求")
            + "建议先按方案 1 培养，再逐步逼近社区标准。")


# ── 6. 多人配装（1~9 人）──────────────────────────────
def recommend_batch(game_id: int, character_ids: list[int], assets: list[dict],
                    user_id: str | None = None) -> list[dict]:
    """一次为多名角色生成配装推荐。"""
    out = []
    for cid in character_ids:
        row = db.query_one("SELECT * FROM entity WHERE id=? AND type='角色'", (cid,))
        if row:
            out.append(recommend_builds(game_id, row, assets, user_id))
    return out


# ── 7. 多队伍配置（1~4 队）─────────────────────────────
def teams_recommend(game_id: int, teams: list[dict], assets: list[dict],
                    session_id: str = "session-demo") -> list[dict]:
    """一次为多支队伍生成整体方案。"""
    out = []
    for idx, t in enumerate(teams):
        member_ids = t.get("members") or []
        if not 2 <= len(member_ids) <= 4:
            continue
        members = [db.query_one("SELECT * FROM entity WHERE id=?", (i,))
                   for i in member_ids]
        members = [m for m in members if m]
        if len(members) < 2:
            continue
        r = team_recommend(game_id, members, assets, t.get("weights"),
                           f"{session_id}-队{idx + 1}")
        r["team_index"] = idx
        out.append(r)
    return out


# ── 8. 材料缺口与培养建议（可复制文本）────────────────────
def material_holdings(assets: list[dict]) -> dict[str, int]:
    """汇总用户已有材料：{材料名: 数量}。"""
    hold: dict[str, int] = {}
    for a in assets:
        if a["type"] == "材料" and a.get("material_qty"):
            name = a.get("name") or ""
            if name:
                hold[name] = hold.get(name, 0) + int(a["material_qty"])
    return hold


def material_gaps(assets: list[dict], entity_id: int, kind: str = "level",
                  target_level: int | None = None,
                  base_target: int | None = None) -> list[tuple[str, int, int]]:
    """按 kb_recipe 配方计算材料缺口：返回 [(材料名, 需要, 已有)]。

    kind: level=角色升级 / skill=技能升级 / weapon=武器升级。
    target_level 低于配方目标时按比例折算（毕业档位贯穿，如休闲→80 级需求更少）。
    base_target：配方无 target 字段时用作折算基准（如技能配方隐含"三技能满 9 级"）。
    """
    row = db.query_one("SELECT recipe FROM kb_recipe WHERE entity_id=? AND kind=?",
                       (entity_id, kind))
    if not row:
        return []
    recipe = json.loads(row["recipe"])
    need_map = dict(recipe.get("材料") or {})
    base = recipe.get("target") or base_target
    if target_level and base and target_level < base:
        ratio = target_level / base
        need_map = {k: max(1, int(v * ratio)) for k, v in need_map.items()}
    hold = material_holdings(assets)
    return [(name, need, hold.get(name, 0)) for name, need in need_map.items()
            if hold.get(name, 0) < need]


def _best_weapon_id(game_id: int, char_id: int) -> int | None:
    row = db.query_one(
        "SELECT weapon_ids FROM kb_build WHERE game_id=? AND char_id=? ORDER BY version DESC",
        (game_id, char_id))
    if not row:
        return None
    ids = json.loads(row["weapon_ids"] or "[]")
    return int(ids[0]) if ids else None


# 首领/BOSS 突破素材名（与 seed.CHAR_MATERIALS 对应；新增角色时同步）
BOSS_MATERIALS = frozenset({
    "未熟之玉", "玄岩之塔", "极寒之核", "雷霆数珠", "灭诤草蔓", "若陀龙王的角",
    "魔偶机心", "常燃火种", "雷光棱镜", "恒常机关之心", "龙王之冕", "飓风之种",
    "藏雷野实", "无相之水·净水之心", "首领突破素材",
})


# 材料刷取优先级（数字越小越优先）
def _material_tier(name: str) -> int:
    if "周本" in name:
        return 1            # 每周限次数，最优先
    if "突破" in name or name in BOSS_MATERIALS:
        return 2            # 首领/BOSS 突破素材
    if ("的教导" in name or "的指引" in name or "的哲学" in name
            or "天赋书" in name or "技能强化" in name):
        return 3            # 天赋书 / 技能强化材料（秘境）
    return 4                # 经验书 / 魔矿 / 货币 / 特产（日常）


def cultivation_advice(game_id: int, character_ids: list[int], assets: list[dict],
                       user_id: str | None = None, tier: str = "standard") -> str:
    """生成可复制的培养建议文本（升级路径 + 材料缺口 + 刷取优先级 + 技能加点 + 配装）。"""
    tier_name = TIER_ALIAS.get(tier, tier)
    lines = [f"【二游毕业指导 · 培养建议】（毕业档位：{tier_name}）"]
    team_gaps: dict[int, dict[str, dict]] = {}   # 队伍整体材料缺口：tier -> 材料 -> {need, chars}
    for cid in character_ids:
        char = db.query_one("SELECT * FROM entity WHERE id=? AND type='角色'", (cid,))
        if not char:
            continue
        # 按所选毕业档位合并标准（档位贯穿：休闲→80 级、标准/极限→90 级等）
        row = db.query_one(
            "SELECT criteria FROM kb_graduation WHERE game_id=? AND char_id=? AND status='生效' "
            "ORDER BY version DESC LIMIT 1", (game_id, cid))
        criteria = json.loads(row["criteria"]) if row else {}
        eff = merge_standard(criteria, {}, tier)
        target_lv = eff.get("level", 90)
        ev = evaluate(char, assets, eff)
        role = next((a for a in assets
                     if a["type"] == "角色" and a["name"] == char["name"]), None)
        cur_lv = role.get("level") if role else None

        lines.append("")
        lines.append(f"■ {char['name']}（毕业度 {ev['score']}）")
        lv_line = f"  等级：当前 Lv.{cur_lv if cur_lv is not None else '?'} → 目标 Lv.{target_lv}"
        if cur_lv is not None and cur_lv >= target_lv:
            lv_line += "（已达标 ✓）"
        lines.append(lv_line)

        # 材料缺口（毕业档位贯穿 target_lv；等级已达标则无需升级材料）
        gaps_level = ([] if (cur_lv is not None and cur_lv >= target_lv)
                      else material_gaps(assets, cid, "level", target_lv))
        # 技能材料按毕业标准中的技能等级目标折算（默认 9/9/9，基准=三技能满 9 级）
        tg = eff.get("talents") or {"normal": 9, "skill": 9, "burst": 9}
        skill_target = round((tg.get("normal", 9) + tg.get("skill", 9)
                              + tg.get("burst", 9)) / 3, 1)
        gaps_skill = material_gaps(assets, cid, "skill", skill_target, base_target=9)
        wid = _best_weapon_id(game_id, cid)
        gaps_weapon = material_gaps(assets, wid, "weapon", target_lv) if wid else []
        lines.append(f"  技能目标：普攻 {tg.get('normal', 9)} / 元素战绩 {tg.get('skill', 9)}"
                     f" / 元素爆发 {tg.get('burst', 9)} 级")
        lines.append("  角色升级材料：" + (
            "；".join(f"{n} 缺 {need - have}" for n, need, have in gaps_level) if gaps_level
            else "充足 ✓"))
        lines.append("  技能升级材料：" + (
            "；".join(f"{n} 缺 {need - have}" for n, need, have in gaps_skill) if gaps_skill
            else "充足 ✓"))
        lines.append("  武器升级材料：" + (
            "；".join(f"{n} 缺 {need - have}" for n, need, have in gaps_weapon) if gaps_weapon
            else "充足 ✓"))

        # 材料刷取优先级（按稀缺度/获取难度排序）
        all_gaps = gaps_level + gaps_skill + gaps_weapon
        if all_gaps:
            tiers: dict[int, list[str]] = {}
            for name, need, have in all_gaps:
                tiers.setdefault(_material_tier(name), []).append(f"{name}×{need - have}")
                tg = team_gaps.setdefault(_material_tier(name), {})
                e = tg.setdefault(name, {"need": 0, "chars": []})
                e["need"] += need - have
                e["chars"].append(char["name"])
            tier_label = {1: "周本材料（每周限次数）", 2: "首领/BOSS 突破素材",
                          3: "天赋书（秘境）", 4: "经验书/魔矿/摩拉/特产（日常）"}
            order = sorted(tiers)
            lines.append("  刷取优先级：" + " → ".join(
                f"{i + 1}) {tier_label.get(t, '其他')}：{'、'.join(tiers[t])}"
                for i, t in enumerate(order)))

        # 技能加点（按角色配置）
        prio = eff.get("talent_priority") or ["E", "A", "Q"]
        tip = "全部加点" if len(prio) >= 3 else f"主{prio[0]}，其余按需"
        lines.append(f"  技能加点顺序：{' → '.join(prio)}（{tip}）")

        # 配装
        rec = recommend_builds(game_id, char, assets, user_id)
        top = rec["builds"][0] if rec["builds"] else None
        if top:
            ms = "、".join(f"{k}={v}" for k, v in top["main_stats"].items())
            lines.append(f"  配装（匹配 {top['hit_rate']}%）：{top['weapons'][0]} / "
                         f"{top['sets'][0]}；主词条 {ms}")
            for g in top["gaps"][:3]:
                lines.append(f"    · {g}")
        # 毕业度主要差距
        for g in ev["gaps"][:3]:
            lines.append(f"    · {g}")

    # 队伍整体刷取优先级（多人时：谁的材料先刷）
    if len(character_ids) > 1 and team_gaps:
        tier_label = {1: "周本材料（每周限次数）", 2: "首领/BOSS 突破素材",
                      3: "天赋书（秘境）", 4: "经验书/魔矿/摩拉/特产（日常）"}
        lines.append("")
        lines.append(f"【队伍刷取优先级】（共 {len(character_ids)} 名角色）")
        for t in sorted(team_gaps):
            parts = [f"{m}×{d['need']}（{'、'.join(sorted(set(d['chars'])))}）"
                     for m, d in team_gaps[t].items()]
            lines.append(f"  {tier_label.get(t, '其他')}：" + "；".join(parts))
    return llm_polish_advice("\n".join(lines))
