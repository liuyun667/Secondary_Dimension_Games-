"""感知→理解管线：OCR(可选) → 粗分类 → 实体链接 → 属性结构化 → analyze 编排。

默认实现零第三方依赖（别名词典 + 规则 + 正则）；重型组件按需启用：
- PaddleOCR：真实截图识别（未装则用 text_lines 模拟）
- fasttext：粗分类（未启用则实体链接优先 + 关键词兜底）
- BERT：实体链接精排（未启用则别名词典子串 + difflib 模糊匹配）
"""
from __future__ import annotations

import difflib
import json
import re

from . import config, database as db

# ── 正则（属性结构化）──────────────────────────────────
LEVEL_RE = re.compile(r"[Ll][Vv]\.?\s*(\d+)|(\d+)\s*级")
RARITY_RE = re.compile(r"[★☆]?\s*([1-5])\s*[星★☆]|([1-5])星|★([1-5])")
SLOTS = ["花", "羽", "沙", "杯", "头"]
MAIN_STATS = ["生命值", "攻击力", "防御力", "暴击率", "暴击伤害", "元素精通",
              "元素充能效率", "火元素伤害加成", "水元素伤害加成", "岩元素伤害加成",
              "物理伤害加成", "雷元素伤害加成", "冰元素伤害加成", "风元素伤害加成"]
SUBSTATS = ["暴击率", "暴击伤害", "攻击力", "防御力", "生命值",
            "元素精通", "元素充能效率"]
# 词条数值解析：如 "暴击率+7.8%"、"生命值 4780"、"攻击力+299"
STAT_VALUE_RE = re.compile(
    r"([\u4e00-\u9fa5]+(?:伤害加成|充能效率)?)\s*[+]?\s*(\d+(?:\.\d+)?)\s*(%)?")
# 强化等级：独立 "+20"（用前后断言避免误抓 "暴击率+7.8%" 里的 +7）
ARTIFACT_LEVEL_RE = re.compile(r"(?<!\d)[+](\d{1,2})(?![\d.])")
# 材料数量："摩拉 x999999" / "突破石 12"
MATERIAL_QTY_RE = re.compile(r"^(.+?)\s*[xX×]?\s*(\d{1,9})$")
# 角色详情：命座 / 天赋等级（如 "命座2"、"天赋 9 10 10"）
CONSTELLATION_RE = re.compile(r"命座\s*([0-6])|命之座\s*([0-6])")
TALENT_RE = re.compile(r"天赋[：:\s]*(\d{1,2})\s*[,，/、\s]+(\d{1,2})\s*[,，/、\s]+(\d{1,2})")


def _parse_material_qty(text: str) -> tuple[str, int | None]:
    m = MATERIAL_QTY_RE.search(text.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return text.strip(), None

MATERIAL_KW = ["摩拉", "经验", "突破材料", "矿石", "结晶", "残渣", "丁尼",
               "提取物", "精华", "祝圣"]


# ── 1. OCR（可选：RapidOCR 优先，paddle 兜底）────────────
_rapid_engine = None
_ocr_engine = None


def _get_rapidocr():
    """RapidOCR（onnxruntime）：不依赖 paddle/torch，推荐（本机 paddle 有 PIR 兼容问题）。"""
    global _rapid_engine
    if _rapid_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_engine = RapidOCR()
    return _rapid_engine


def _get_ocr():
    """PaddleOCR 兜底。"""
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR  # 3.x：无 use_angle_cls / show_log
        _ocr_engine = PaddleOCR(
            lang="ch",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    return _ocr_engine


def _decode_to_array(image_bytes: bytes):
    import io
    import numpy as np
    from PIL import Image
    return np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))


def extract_lines(image_bytes: bytes | None = None, simulated: list[str] | None = None) -> list[str]:
    """图片 → 文本行。优先 RapidOCR；未装则走 PaddleOCR；未传图用 simulated。"""
    if simulated:
        return [ln.strip() for ln in simulated if ln and ln.strip()]
    if image_bytes:
        arr = _decode_to_array(image_bytes)
        # 1) RapidOCR（推荐）
        try:
            engine = _get_rapidocr()
            result, _ = engine(arr)
            lines = []
            if result:
                for item in result:
                    text = item[1] if len(item) > 1 else ""
                    score = item[2] if len(item) > 2 else 1.0
                    if text and (score is None or score >= 0.5):
                        lines.append(text.strip())
            if lines:
                return lines
            raise RuntimeError("未识别到文本，请确认画面清晰")
        except ImportError:
            pass  # 无 rapidocr → 走 paddle
        # 2) PaddleOCR 兜底
        try:
            ocr = _get_ocr()
            result = ocr.predict(arr)
            lines = []
            for r in result:
                if isinstance(r, dict):          # 3.x：rec_texts / rec_scores
                    for text, score in zip(r.get("rec_texts") or [], r.get("rec_scores") or []):
                        if score is None or score >= 0.5:
                            lines.append(text)
                elif isinstance(r, list):        # 2.x 兼容
                    for item in r:
                        try:
                            lines.append(item[1][0])
                        except Exception:
                            continue
            return lines
        except ImportError:
            if config.SIMULATE_OCR:
                raise RuntimeError("未安装文字识别组件（rapidocr / paddleocr）；请用「粘贴文本」或「自动导入」")
            raise
    return []


# ── 2. 实体链接（默认：别名词典子串 + difflib 兜底）──────
def match_entity(text: str, game_id: int) -> dict | None:
    """文本 → 库内唯一实体。最长别名子串匹配优先；无命中时模糊匹配兜底。"""
    entities = db.query("SELECT * FROM entity WHERE game_id=?", (game_id,))
    best = None
    for e in entities:
        names = [e["name"]] + json.loads(e["aliases"] or "[]")
        for n in names:
            if n and n in text:
                if best is None or len(n) > len(best[0]):
                    best = (n, e)
    if best:
        return best[1]

    # 模糊匹配兜底（difflib，stdlib）：对已知实体名做相似度匹配
    known = [(e["name"], e) for e in entities]
    text_clean = re.sub(r"[Lv.0-9★☆%+\s（）()·\-]", "", text)
    if not text_clean:
        return None
    close = difflib.get_close_matches(text_clean, [n for n, _ in known], n=1, cutoff=0.75)
    if close:
        return next(e for n, e in known if n == close[0])
    return None


# ── 3. 粗分类（默认：实体类型优先 + 关键词兜底）──────────
def classify(text: str, game_id: int) -> str:
    ent = match_entity(text, game_id)
    if ent:
        return ent["type"]
    if config.USE_FASTTEXT:
        return _classify_fasttext(text)  # 可选：fasttext 模型（TODO 训练接入）
    if any(k in text for k in MATERIAL_KW):
        return "材料"
    if LEVEL_RE.search(text):
        return "角色"
    return "其他"


_fasttext_model = None  # 模块级缓存（组A1：避免每行重复加载模型）


def _classify_fasttext(text: str) -> str:  # pragma: no cover - 可选组件
    global _fasttext_model
    import fasttext  # type: ignore
    if _fasttext_model is None:
        _fasttext_model = fasttext.load_model(config.FASTTEXT_MODEL)
    label, _ = _fasttext_model.predict(text)
    return label[0].replace("__label__", "")


# ── 4. 属性结构化（正则 + 规则）────────────────────────
# 部位词别名 → 规范化槽位（组A2：覆盖「理之冠/冠」等真实名称）
SLOT_ALIASES = {"花": "花", "生之花": "花", "羽": "羽", "死之羽": "羽",
                "沙": "沙", "时之沙": "沙", "杯": "杯", "空之杯": "杯",
                "头": "头", "冠": "头", "理之冠": "头"}


def _find_slot(text: str) -> str | None:
    for kw, canon in SLOT_ALIASES.items():
        if kw in text:
            return canon
    return None


def _parse_main_stat(text: str) -> tuple[str | None, float | None]:
    """主词条：① 括号形式（词条名 [数值]）优先；② 无括号：取首个带数值的词条。"""
    m = re.search(r"（([^）]*)）|\(([^)]*)\)", text)
    if m:
        content = (m.group(1) or m.group(2) or "").strip()
        for name in MAIN_STATS:
            if content.startswith(name):
                rest = content[len(name):].strip()
                nm = re.match(r"([+]?\s*\d+(?:\.\d+)?)\s*(%)?", rest)
                if nm:
                    return name, float(nm.group(1).replace("+", "").strip())
                return name, None
    # 无括号：取文本中第一个「词条名 + 数值」
    for mm in STAT_VALUE_RE.finditer(text):
        name, num = mm.group(1), mm.group(2)
        if name in MAIN_STATS:
            return name, float(num)
    # 无括号无数值：取第一个出现的词条名
    for name in MAIN_STATS:
        if name in text:
            return name, None
    return None, None


def structure(text: str, category: str, entity: dict) -> dict:
    level = None
    m = LEVEL_RE.search(text)
    if m:
        level = int(m.group(1) or m.group(2))

    rarity = entity.get("rarity") or 0
    m = RARITY_RE.search(text)
    if m:
        rarity = int(next(g for g in m.groups() if g))

    slot = _find_slot(text)

    main_stat, main_value = _parse_main_stat(text)

    # 副词条：带数值的结构化条目，如 {name: 暴击率, value: 7.8, percent: True}
    substats = []
    for m in STAT_VALUE_RE.finditer(text):
        name, num, pct = m.group(1), m.group(2), m.group(3)
        if name in SUBSTATS and name != main_stat:
            substats.append({"name": name, "value": float(num), "percent": bool(pct)})

    # 强化等级（圣遗物 +20 / 武器精炼另算）
    artifact_level = None
    m = ARTIFACT_LEVEL_RE.search(text)
    if m:
        artifact_level = int(m.group(1))

    return {"level": level, "artifact_level": artifact_level, "rarity": rarity,
            "slot": slot, "main_stat": main_stat, "main_stat_value": main_value,
            "substats": substats}


# ── 5. analyze 编排 ───────────────────────────────────
def analyze_lines(lines: list[str], game_id: int, session_id: str = "session-demo") -> dict:
    """文本行 → 资产列表 + 未解析文本。"""
    assets, unresolved = [], []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        ent = match_entity(text, game_id)
        if ent is None:
            if classify(text, game_id) == "材料":
                name, qty = _parse_material_qty(text)
                assets.append({
                    "entity_id": None, "type": "材料", "name": name,
                    "material_qty": qty,
                    "level": None, "rarity": None, "slot": None,
                    "main_stat": None, "substats": [], "conf": 0.6, "raw_text": text,
                })
            else:
                unresolved.append(text)
            continue
        cat = ent["type"]
        attrs = structure(text, cat, ent)
        asset = {
            "entity_id": ent["id"], "type": cat, "name": ent["name"],
            "level": attrs["level"], "artifact_level": attrs["artifact_level"],
            "rarity": attrs["rarity"], "slot": attrs["slot"],
            "main_stat": attrs["main_stat"], "main_stat_value": attrs["main_stat_value"],
            "substats": attrs["substats"],
            "conf": 0.98, "raw_text": text,
        }
        if cat == "角色":  # 角色详情：命座 / 天赋等级
            m = CONSTELLATION_RE.search(text)
            if m:
                asset["constellation"] = int(m.group(1) or m.group(2) or 0)
            m = TALENT_RE.search(text)
            if m:
                asset["talents"] = [int(x) for x in m.groups()]
        assets.append(asset)
        db.execute(
            "INSERT INTO user_asset (session_id, game_id, entity_id, level, rarity, "
            "slot, stats, raw_text, conf, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session_id, game_id, ent["id"], attrs["level"], attrs["rarity"],
             attrs["slot"], json.dumps({"main_stat": attrs["main_stat"],
                                        "main_stat_value": attrs["main_stat_value"],
                                        "artifact_level": attrs["artifact_level"],
                                        "substats": attrs["substats"],
                                        "constellation": asset.get("constellation"),
                                        "talents": asset.get("talents"),
                                        "material_qty": asset.get("material_qty")},
                                       ensure_ascii=False),
             text, asset["conf"], db.now_iso()))
    return {"assets": assets, "unresolved": unresolved}
