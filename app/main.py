"""FastAPI 入口：全部路由（对应文档 §5）。

启动：uvicorn app.main:app --reload --port 8000
文档：http://localhost:8000/docs
"""
from __future__ import annotations

import base64
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import database as db, engine, pipeline, sample_data, seed
from .schemas import (AdviceReq, AnalyzeReq, AssetsSaveReq, AutoClickReq,
                      CollectReq, FeedbackReq, GraduateReq, RecommendBatchReq, RecommendReq,
                      StandardsReq, TeamReq, TeamsReq, TestDataReq)

app = FastAPI(title="二游毕业指导", version="1.1.0",
              description="多游戏角色毕业指导：资产识别 → 毕业度评估 → 配装推荐 → 队伍配置",
              docs_url="/api/docs", redoc_url="/api/redoc")   # Swagger 挪开，/docs 留给文档页

app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    seed.seed_all()  # 建表 + 无数据时灌入种子


def _entity_or_404(eid: int) -> dict:
    row = db.query_one("SELECT * FROM entity WHERE id=?", (eid,))
    if not row:
        raise HTTPException(404, f"实体不存在: {eid}")
    return row


# ── 基础 ──────────────────────────────────────────────
@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/games")
def list_games() -> list[dict]:
    return db.query("SELECT id, code, name, weapon_name, equipment_name, adapter_key, "
                    "max_team_size FROM game ORDER BY id")


@app.get("/api/v1/sample")
def sample_lines(game_id: int) -> dict:
    """返回该游戏的示例账户文本行（前端「导入示例账户」用）。"""
    g = db.query_one("SELECT name FROM game WHERE id=?", (game_id,))
    if not g:
        raise HTTPException(404, "游戏不存在")
    return {"game_id": game_id, "lines": sample_data.lines_for(g["name"])}


@app.post("/api/v1/collect")
def collect(req: CollectReq) -> dict:
    """采集插件入口：file/clipboard/sample/ocr → 文本行 → 识别管线。"""
    from .collectors import COLLECTORS
    if req.method not in COLLECTORS:
        raise HTTPException(400, f"未知采集方式: {req.method}（可选 {'/'.join(COLLECTORS)}）")
    try:
        return collect_runner(req.game_id, req.method, req.payload)
    except Exception as e:
        raise HTTPException(400, f"采集失败：{e}")


def collect_runner(game_id: int, method: str, payload: dict | None) -> dict:
    """执行采集插件并返回识别结果（与 /api/v1/analyze 同构）。"""
    from .collectors import run_collector
    return run_collector(game_id, method, payload)


@app.get("/api/v1/characters")
def list_characters(game_id: int) -> list[dict]:
    return db.query(
        "SELECT id, name, rarity FROM entity WHERE game_id=? AND type='角色' ORDER BY rarity DESC, id",
        (game_id,))


# ── 资产识别 ──────────────────────────────────────────
@app.post("/api/v1/analyze")
def analyze(req: AnalyzeReq) -> dict:
    if req.image and not req.text_lines:
        try:
            img = base64.b64decode(req.image)
            lines = pipeline.extract_lines(image_bytes=img)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"图片识别失败：{e}")
    elif req.text_lines:
        lines = pipeline.extract_lines(simulated=req.text_lines)
    else:
        raise HTTPException(400, "需提供 image 或 text_lines")
    return pipeline.analyze_lines(lines, req.game_id, req.session_id)


# ── 毕业度评估（支持自定义标准）─────────────────────────
@app.post("/api/v1/graduate")
def graduate(req: GraduateReq) -> dict:
    char = _entity_or_404(req.character_id)
    if req.standard:  # 临时标准（不落库）：{tier?, overrides?}
        base = db.query_one(
            "SELECT * FROM kb_graduation WHERE game_id=? AND char_id=? AND status='生效' "
            "ORDER BY version DESC LIMIT 1", (req.game_id, req.character_id))
        criteria = json.loads(base["criteria"]) if base else {}
        eff = engine.merge_standard(criteria, req.standard.get("overrides"),
                                    req.standard.get("tier", "standard"))
        meta = {"tier": req.standard.get("tier", "standard")}
    else:
        eff, meta = engine.load_effective_standard(req.game_id, req.character_id,
                                                   req.user_id)
    result = engine.evaluate(char, req.assets, eff)
    result["standard"] = {"tier": meta["tier"],
                          "tier_name": engine.TIER_ALIAS.get(meta["tier"], meta["tier"])}
    # 该角色主要属性（毕业标准关注的副词条）——前端用于把非主要属性置灰、不参与评估
    result["key_stats"] = list((eff.get("substat_targets") or {}).keys())
    return result


# ── 配装推荐 ──────────────────────────────────────────
@app.post("/api/v1/recommend")
def recommend(req: RecommendReq) -> dict:
    char = _entity_or_404(req.character_id)
    return engine.recommend_builds(req.game_id, char, req.assets, req.user_id)


# ── 自定义毕业标准（§3.7.1）────────────────────────────
@app.get("/api/v1/standards")
def get_standard(user_id: str, game_id: int, character_id: int) -> dict:
    row = db.query_one(
        "SELECT tier, overrides, version, updated_at FROM user_standard "
        "WHERE user_id=? AND game_id=? AND char_id=? ORDER BY updated_at DESC LIMIT 1",
        (user_id, game_id, character_id))
    if not row:
        return {"tier": "standard", "overrides": {}, "exists": False}
    return {"tier": row["tier"], "overrides": json.loads(row["overrides"] or "{}"),
            "version": row["version"], "updated_at": row["updated_at"], "exists": True}


@app.put("/api/v1/standards")
def put_standard(req: StandardsReq) -> dict:
    if req.tier not in engine.TIER_ALIAS:
        raise HTTPException(400, f"未知档位: {req.tier}（可选 casual/standard/extreme/custom）")
    db.execute(
        "INSERT INTO user_standard (user_id, game_id, char_id, tier, overrides, "
        "version, updated_at) VALUES (?,?,?,?,?,?,?)",
        (req.user_id, req.game_id, req.character_id, req.tier,
         json.dumps(req.overrides, ensure_ascii=False), "5.0", db.now_iso()))
    return {"saved": True, "tier": req.tier, "overrides": req.overrides}


# ── 队伍整体配置（§3.7.2）──────────────────────────────
def _team_size(game_id: int) -> int:
    g = db.query_one("SELECT max_team_size FROM game WHERE id=?", (game_id,))
    return g["max_team_size"] if g else 4


@app.post("/api/v1/team/recommend")
def team_recommend(req: TeamReq) -> dict:
    max_size = _team_size(req.game_id)
    if not 2 <= len(req.members) <= max_size:
        raise HTTPException(400, f"该游戏每队需 2~{max_size} 人（当前 {len(req.members)}）")
    members = [_entity_or_404(i) for i in req.members]
    return engine.team_recommend(req.game_id, members, req.assets,
                                 req.weights, req.session_id)


# ── 反馈闭环 ───────────────────────────────────────────
@app.post("/api/v1/feedback")
def feedback(req: FeedbackReq) -> dict:
    if req.action not in ("采纳", "拒绝", "纠正"):
        raise HTTPException(400, "action 需为 采纳/拒绝/纠正")
    db.execute(
        "INSERT INTO user_feedback (session_id, target_type, target_id, action, "
        "correction, created_at) VALUES (?,?,?,?,?,?)",
        (req.session_id, req.target_type, req.target_id, req.action,
         json.dumps(req.correction, ensure_ascii=False) if req.correction else None,
         db.now_iso()))
    return {"saved": True}


# ── 资产存取与删除（游戏账户数据，四类分开：角色/武器/装备/材料）────
def _row_to_asset(row: dict) -> dict:
    stats = json.loads(row["stats"]) if row["stats"] else {}
    ent = db.query_one("SELECT type, name FROM entity WHERE id=?",
                       (row["entity_id"],)) if row["entity_id"] else None
    return {
        "entity_id": row["entity_id"],
        "type": row["type"] or (ent["type"] if ent else "材料"),
        "name": ent["name"] if ent else (row["raw_text"] or ""),
        "level": row["level"], "artifact_level": stats.get("artifact_level"),
        "rarity": row["rarity"], "slot": row["slot"],
        "set": stats.get("set"),
        "main_stat": stats.get("main_stat"),
        "main_stat_value": stats.get("main_stat_value"),
        "substats": stats.get("substats") or [],
        "constellation": stats.get("constellation"),
        "talents": stats.get("talents"),
        "material_qty": stats.get("material_qty"),
        "weapon_type": stats.get("weapon_type"),
        "refinement": stats.get("refinement"),
        "base_atk": stats.get("base_atk"),
        "passive": stats.get("passive"),
        "source": stats.get("source"),
        "upgrade": stats.get("upgrade"),
        "conf": row["conf"], "raw_text": row["raw_text"],
    }


@app.get("/api/v1/assets")
def get_assets(user_id: str, game_id: int) -> dict:
    rows = db.query(
        "SELECT * FROM user_asset WHERE session_id=? AND game_id=? ORDER BY id",
        (user_id, game_id))
    return {"assets": [_row_to_asset(r) for r in rows]}


@app.post("/api/v1/assets")
def save_assets(req: AssetsSaveReq) -> dict:
    db.execute("DELETE FROM user_asset WHERE session_id=? AND game_id=?",
               (req.user_id, req.game_id))
    for a in req.assets:
        db.execute(
            "INSERT INTO user_asset (session_id, game_id, type, entity_id, level, rarity, "
            "slot, stats, raw_text, conf, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (req.user_id, req.game_id, a.get("type") or "材料", a.get("entity_id"),
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
                         "source": a.get("source")}, ensure_ascii=False),
             a.get("raw_text") or a.get("name"), a.get("conf"), db.now_iso()))
    return {"saved": len(req.assets)}


@app.delete("/api/v1/assets")
def delete_assets(user_id: str, game_id: int) -> dict:
    before = db.query("SELECT COUNT(*) AS c FROM user_asset WHERE session_id=? AND game_id=?",
                      (user_id, game_id))[0]["c"]
    db.execute("DELETE FROM user_asset WHERE session_id=? AND game_id=?", (user_id, game_id))
    return {"deleted": before}


# ── 测试数据（点击时实时生成：66 角色/150 武器/1000 圣遗物/400 材料）──
@app.post("/api/v1/test-data/generate")
def generate_test_data(req: TestDataReq) -> dict:
    from . import test_data
    try:
        n = test_data.generate_test_account(req.session, req.game_id)
        return {"generated": n, "session": req.session, "game_id": req.game_id,
                "created_at": db.now_iso()}
    except Exception as e:
        raise HTTPException(400, f"测试数据生成失败：{e}")


# ── 多人配装（1~9 人）──────────────────────────────────
@app.post("/api/v1/recommend/batch")
def recommend_batch(req: RecommendBatchReq) -> dict:
    if not 1 <= len(req.character_ids) <= 9:
        raise HTTPException(400, "配装人数需 1~9 人")
    return {"results": engine.recommend_batch(req.game_id, req.character_ids,
                                              req.assets, req.user_id)}


# ── 多队伍配置（1~4 队）────────────────────────────────
@app.post("/api/v1/teams/recommend")
def teams_recommend(req: TeamsReq) -> dict:
    if not 1 <= len(req.teams) <= 4:
        raise HTTPException(400, "队伍数量需 1~4 队")
    max_size = _team_size(req.game_id)
    for t in req.teams:
        if not 2 <= len(t.members) <= max_size:
            raise HTTPException(400, f"该游戏每队需 2~{max_size} 人（当前 {len(t.members)}）")
    return {"teams": engine.teams_recommend(req.game_id,
                                            [t.model_dump() for t in req.teams],
                                            req.assets, req.session_id)}


# ── 培养建议（可复制文本）────────────────────────────────
@app.post("/api/v1/advice")
def advice(req: AdviceReq) -> dict:
    if not 1 <= len(req.character_ids) <= 9:
        raise HTTPException(400, "建议角色数需 1~9 人")
    return {"advice": engine.cultivation_advice(
        req.game_id, req.character_ids, req.assets, req.user_id, req.tier)}


# ── 伴生工具自动点击（网页一键开启，读屏/详情采集）──────────
@app.post("/api/v1/auto-click/start")
def auto_click_start(req: AutoClickReq) -> dict:
    """启动 auto_export.py --auto-detail（subprocess，参数白名单；断点续采见 resume）。"""
    from . import auto_click
    try:
        return auto_click.start(req.game, req.window, req.output,
                                req.max_items, req.resume, req.max_miss,
                                req.viewport)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/v1/auto-click/status")
def auto_click_status() -> dict:
    from . import auto_click
    return auto_click.status()


@app.post("/api/v1/auto-click/stop")
def auto_click_stop() -> dict:
    from . import auto_click
    return auto_click.stop()


# ── 文档页（局域网可访问：http://<本机IP>:8000/docs）──────
# 必须在 StaticFiles mount 之前注册，否则被 "/" 的 catch-all 吞掉
_DOCS = [
    ("项目介绍", "二游毕业指导-项目介绍.md"),
    ("技术文档", "二游毕业指导.md"),
    ("数据采集决策树", "二游毕业指导-数据采集决策树.md"),
    ("项目文件说明", "二游毕业指导-项目文件说明.md"),
]
_ROOT = Path(__file__).resolve().parent.parent / "docs"   # 文档目录（项目内 docs/）


@app.get("/docs")
def docs(doc: str = "二游毕业指导-项目介绍.md") -> HTMLResponse:
    from . import md_render
    name = next((n for _, n in _DOCS if n == doc), _DOCS[0][1])
    path = _ROOT / name
    text = path.read_text(encoding="utf-8") if path.exists() else "# 文档不存在"
    nav = [(label, fname, fname == name) for label, fname in _DOCS]
    title = next((label for label, fname in _DOCS if fname == name), name)
    return HTMLResponse(md_render.docs_page(title, nav, md_render.render_md(text)))


# ── 前端页面（纯中文界面）───────────────────────────────
# 放在所有 API 路由之后挂载，避免抢占 /api/* 与 /docs
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
