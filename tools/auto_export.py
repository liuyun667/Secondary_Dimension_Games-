"""伴生自动导出器 v2 —— 自动点击详情 + OCR 拿完整属性（参考莫娜占卜铺思路）。

浏览器只能"看"不能"点"；本工具运行在**你自己的电脑**上，用 pyautogui 模拟点击
游戏窗口：循环「点击列表物品 → 进入详情页 → 截图 OCR → 解析完整属性 → 返回列表 → 下一件」，
全程无需用户参与，导出 JSON 供网页「自动导入」。

模式：
  python tools/auto_export.py --text-lines sample_detail.txt --output a.json   # 离线测试（可验证）
  python tools/auto_export.py --pages 20 --game genshin --window 原神           # 列表整页扫描（仅名称/等级）
  python tools/auto_export.py --auto-detail --game genshin --window 原神       # 自动点击详情（完整属性，推荐）
  python tools/auto_export.py --auto-detail --resume --game genshin --window 原神   # 中断后续采

自动点击模式特性：每件采集后实时写断点文件 <输出>.state.json，Ctrl+C/异常中断后加
--resume 可从断点继续（跳过已采件数、保留已采数据）；连续 N 件识别失败自动停止（--max-miss）。
进度与预计剩余时间每 10 件打印一次。

合规边界：只读截图 + 模拟「点击查看详情 / 返回」，**不注入、不修改游戏文件、不改变账号数据**；
仅在你自己的电脑、自己的账号上使用。坐标需按实际游戏窗口校准（见 --calibrate）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

# ── 词条/部位常量 ─────────────────────────────────────
SLOT_ALIASES = {"花": "花", "生之花": "花", "羽": "羽", "死之羽": "羽",
                "沙": "沙", "时之沙": "沙", "杯": "杯", "空之杯": "杯",
                "头": "头", "冠": "头", "理之冠": "头",
                "1号盘": "1", "2号盘": "2", "3号盘": "3", "4号盘": "4",
                "5号盘": "5", "6号盘": "6"}
SUBSTAT_NAMES = ["暴击率", "暴击伤害", "攻击力", "防御力", "生命值",
                 "元素精通", "元素充能效率"]
MAIN_NAMES = SUBSTAT_NAMES + ["火元素伤害加成", "水元素伤害加成", "冰元素伤害加成",
                              "雷元素伤害加成", "风元素伤害加成", "岩元素伤害加成",
                              "物理伤害加成", "草元素伤害加成"]
STAT_RE = re.compile(
    r"([\u4e00-\u9fa5]+(?:伤害加成|充能效率)?)\s*[+]?\s*(\d+(?:\.\d+)?)\s*(%)?")
LEVEL_RE = re.compile(r"(?<!\d)[+](\d{1,2})(?![\d.])")

# 各游戏点击策略（坐标为窗口内归一化比例，需按实际 UI 校准）
CLICK_STRATEGIES = {
    "genshin": {"grid_cols": 6, "grid_rows": 5, "start": (0.06, 0.18),
                "cell": (0.145, 0.155), "back": "esc", "page": "pagedown",
                "wait_detail": 0.9, "wait_list": 0.5},
    "zzz": {"grid_cols": 5, "grid_rows": 4, "start": (0.07, 0.20),
            "cell": (0.17, 0.185), "back": "esc", "page": "pagedown",
            "wait_detail": 0.9, "wait_list": 0.5},
    "wuthering": {"grid_cols": 6, "grid_rows": 5, "start": (0.06, 0.18),
                  "cell": (0.145, 0.155), "back": "esc", "page": "pagedown",
                  "wait_detail": 0.9, "wait_list": 0.5},
}


# ── 1. OCR：截图 → 带坐标文本行（RapidOCR 优先，paddle 兜底）──
def ocr_screen(image_bytes: bytes) -> list[tuple[float, float, str]]:
    import numpy as np
    from PIL import Image
    arr = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    items: list[tuple[float, float, str]] = []

    def _collect(box, text, score):
        if score < 0.5 or not text.strip():
            return
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append((min(ys), min(xs), text.strip()))

    try:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(arr)
        if result:
            for item in result:
                _collect(item[0], item[1], item[2] if len(item) > 2 else 1.0)
        items.sort(key=lambda t: (t[0], t[1]))
        return items
    except ImportError:
        pass
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="ch", use_doc_orientation_classify=False,
                    use_doc_unwarping=False, use_textline_orientation=False)
    result = ocr.predict(arr)
    for r in result:
        if isinstance(r, dict):
            polys = r.get("rec_polys") or r.get("dt_polys") or []
            for box, text, score in zip(polys, r.get("rec_texts") or [],
                                        r.get("rec_scores") or []):
                _collect(box, text, score or 0.0)
        elif isinstance(r, list):
            for entry in r:
                try:
                    box, (text, conf) = entry[0], entry[1]
                    _collect(box, text, conf)
                except Exception:
                    continue
    items.sort(key=lambda t: (t[0], t[1]))
    return items


# ── 2. 详情页/卡片解析 ─────────────────────────────────
def parse_cards(texts: list) -> list[dict]:
    """把详情页/卡片 OCR 文本解析成物品条目。

    布局（详情页从上到下）：套装名 → 部位(或盘号) → 主属性+值 → 副词条×N → +强化等级。
    启发式：出现部位词/盘号的一行视为新条目起点；其前一行（缓冲）为套装名。
    """
    if texts and all(isinstance(t, str) for t in texts):
        texts = [(i, 0, t) for i, t in enumerate(texts)]
    cards: list[dict] = []
    cur: dict | None = None
    pending: list[str] = []

    for _y, _x, text in texts:
        slot = next((canon for kw, canon in SLOT_ALIASES.items() if kw in text), None)
        if slot is None and re.fullmatch(r"[1-6](号盘)?", text):
            slot = text[0]
        if slot:
            if cur:
                cards.append(cur)
            cur = {"set": pending[-1] if pending else "", "slot": slot,
                   "main": None, "main_value": None, "level": None, "substats": []}
            pending = []
            continue
        m = LEVEL_RE.search(text)
        if m and not STAT_RE.search(text):
            if cur:
                cur["level"] = int(m.group(1))
            continue
        sm = STAT_RE.search(text)
        if sm and sm.group(1) in MAIN_NAMES:
            if cur:
                name, num, pct = sm.group(1), float(sm.group(2)), bool(sm.group(3))
                if cur["main"] is None:
                    cur["main"], cur["main_value"] = name, num
                else:
                    cur["substats"].append({"name": name, "value": num, "percent": pct})
            continue
        pending.append(text)   # 套装名等未识别行缓冲
    if cur:
        cards.append(cur)
    return cards


# ── 3. 自动点击详情（核心：无需用户参与，含断点续采/进度/容错）──
def _need(pip_name: str, module: str | None = None):
    """懒加载 pyautogui/pygetwindow：缺失时给出安装提示而不是裸 Traceback。"""
    try:
        return __import__(module or pip_name)
    except ImportError:
        raise SystemExit(
            f"缺少依赖 {pip_name}：请先执行  pip install {pip_name}  （当前 Python: {sys.executable}）")


def _find_window(title: str):
    gw = _need("pygetwindow")
    wins = [w for w in gw.getWindowsWithTitle(title) if w.visible and w.width > 100]
    if not wins:
        # 云游戏场景：窗口标题是客户端名（如 网易云游戏/START），不是游戏名。
        # 找不到时列出可见窗口候选，方便用户填对标题。
        cands = [w.title for w in gw.getAllWindows()
                 if w.visible and w.width > 100 and w.title.strip()]
        shown = "；".join(sorted(set(cands))[:20])
        tip = ""
        if any(k in "".join(cands) for k in ("Edge", "Chrome", "Firefox", "浏览器")):
            tip = ("\n检测到浏览器窗口：浏览器所有标签共用一个窗口，标题只显示【活动标签】。\n"
                   "请把云原神标签【切到前台】再试（窗口标题会变成 云·原神 … - Microsoft Edge），"
                   "或把标签拖成独立窗口更稳。")
        raise SystemExit(
            f"未找到游戏窗口「{title}」，请确认游戏已打开且窗口标题正确\n"
            f"当前可见窗口有：{shown or '（无）'}"
            f"{tip}\n"
            f"云游戏请用客户端窗口标题（如 网易云游戏/START/WeGame 云游戏），并先跑 --calibrate 验证")
    return wins[0]


def _state_path(output: str) -> str:
    return output + ".state.json"


def _load_state(output: str) -> tuple[list[dict], int]:
    """断点续采：从 state 文件恢复 已收集数据 + 起始下标。"""
    artifacts: list[dict] = []
    start = 0
    if os.path.exists(_state_path(output)):
        try:
            st = json.load(open(_state_path(output), encoding="utf-8"))
            start = int(st.get("item_index", 0))
            artifacts = st.get("artifacts", [])
        except Exception:
            start = 0
    return artifacts, start


def _save_state(output: str, item_index: int, artifacts: list[dict]) -> None:
    """每件采集后写断点：记录已扫描到的下标 + 已收集数据本体，
    中断（Ctrl+C/异常）后 --resume 可从断点继续且不丢数据。"""
    json.dump({"item_index": item_index,
               "artifacts_count": len(artifacts),
               "artifacts": artifacts},
              open(_state_path(output), "w", encoding="utf-8"))


def _parse_viewport(spec: str | None) -> tuple[float, float, float, float] | None:
    """解析 --viewport "x,y,w,h"（窗口内百分比，如 0,12,100,82 = 从 12% 高起、宽 100%、高 82%）。"""
    if not spec:
        return None
    parts = [float(x) for x in spec.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise SystemExit("--viewport 需为 x,y,w,h 四个百分比，如 0,12,100,82")
    if not (0 <= parts[0] <= 100 and 0 <= parts[1] <= 100 and 0 < parts[2] <= 100 and 0 < parts[3] <= 100):
        raise SystemExit("--viewport 取值需在 0~100 内，宽高大于 0")
    return tuple(parts)  # type: ignore[return-value]


def auto_detail(game: str, window_title: str, output: str,
                max_items: int = 200, calibrate: bool = False,
                resume: bool = False, max_miss: int = 10,
                viewport: str | None = None,
                fail_safe: bool = False) -> int:
    pyautogui = _need("pyautogui")
    # fail-safe：鼠标到屏幕左上角即中断（防失控）。自用采集工具默认关闭，
    # 否则鼠标停在角落会误触发；需要时用 --fail-safe 开启，触发后优雅保存断点。
    pyautogui.FAILSAFE = fail_safe
    from PIL import ImageGrab

    vp = _parse_viewport(viewport)
    strat = CLICK_STRATEGIES.get(game, CLICK_STRATEGIES["genshin"])
    win = _find_window(window_title)
    left, top, width, height = win.left, win.top, win.width, win.height
    # 游戏画面区域（浏览器/云游戏：窗口含标签栏等 UI，用 viewport 裁剪到画面本身）
    if vp:
        bx = left + int(width * vp[0] / 100)
        by = top + int(height * vp[1] / 100)
        bw = int(width * vp[2] / 100)
        bh = int(height * vp[3] / 100)
    else:
        bx, by, bw, bh = left, top, width, height

    def pos(i: int) -> tuple[int, int]:
        col = i % strat["grid_cols"]
        row = (i // strat["grid_cols"]) % strat["grid_rows"]
        x = bx + int(bw * (strat["start"][0] + col * strat["cell"][0]))
        y = by + int(bh * (strat["start"][1] + row * strat["cell"][1]))
        return x, y

    if calibrate:
        print(f"窗口「{window_title}」: 左上({left},{top}) 尺寸 {width}x{height}")
        if vp:
            print(f"画面区域(viewport): ({bx},{by}) 尺寸 {bw}x{bh}"
                  f"（已裁剪窗口内 {vp[0]:.0f}%,{vp[1]:.0f}% 起、宽 {vp[2]:.0f}%、高 {vp[3]:.0f}%）")
        print("策略:", json.dumps(strat, ensure_ascii=False))
        print("请对照游戏网格，若点偏，编辑本文件 CLICK_STRATEGIES 中的 start/cell 比例后重试。")
        print("浏览器/云游戏非全屏时，可用 --viewport x,y,w,h 指定游戏画面在窗口内的百分比区域"
              "（如 --viewport 0,12,100,82）。")
        return 0

    # 断点续采
    artifacts, start_index = (_load_state(output) if resume else ([], 0))
    if start_index > 0:
        print(f"↻ 续采：从第 {start_index} 件继续（已收集 {len(artifacts)} 条）。"
              f"请确认游戏停在列表同一位置。")
    print(f"开始自动采集（游戏={game}，目标 {max_items} 件，每件约 "
          f"{strat['wait_detail'] + strat['wait_list']}s）...")
    per_page = strat["grid_cols"] * strat["grid_rows"]
    t0 = time.time()
    miss = 0
    for i in range(start_index, max_items):
        try:
            # 翻页：每页末回到下一页开头（下标即可推导，续采也一致）
            if i and i % per_page == 0:
                pyautogui.press(strat["page"])
                time.sleep(strat["wait_list"])
            x, y = pos(i % per_page)
            pyautogui.click(x, y)                       # 点击进入详情
            time.sleep(strat["wait_detail"])
            img = ImageGrab.grab(bbox=(bx, by, bx + bw, by + bh))
            buf = io.BytesIO()
            img.save(buf, "JPEG")
            texts = ocr_screen(buf.getvalue())
            card = parse_cards(texts)
            if card:
                artifacts.extend(card)
                miss = 0
            else:
                miss += 1
                if miss >= max_miss:
                    print(f"连续 {max_miss} 件未识别详情（可能已到列表末尾或布局变化），"
                          f"停止采集；可用 --resume 继续。")
                    _save_state(output, i + 1, artifacts)
                    break
            pyautogui.press(strat["back"])               # 返回列表
            time.sleep(strat["wait_list"])
            _save_state(output, i + 1, artifacts)        # 每件保存断点
        except pyautogui.FailSafeException:
            # 仅在 --fail-safe 开启时可能触发：鼠标移到屏幕左上角 = 紧急停止
            print("紧急停止：鼠标已移到屏幕左上角（fail-safe 触发），已保存断点；"
                  "可用 --resume 从第 {} 件继续。".format(i))
            _save_state(output, i, artifacts)            # 当前件未完成，从 i 续采
            break

        # 进度 + 预计剩余时间
        done = i + 1 - start_index
        if done > 0 and (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            eta = elapsed / done * (max_items - i - 1)
            print(f"  进度 {i + 1}/{max_items} ｜ 已收集 {len(artifacts)} 条 "
                  f"｜ 剩余约 {eta / 60:.1f} 分钟")

    with open(output, "w", encoding="utf-8") as f:
        json.dump({"game": game, "characters": [], "weapons": [],
                   "artifacts": artifacts, "materials": []}, f,
                  ensure_ascii=False, indent=2)
    print(f"完成：{len(artifacts)} 条 → {output}（网页「自动导入」选此文件）")
    if start_index == 0 and len(artifacts) > 0:
        print(f"断点文件：{_state_path(output)}（中断后可 --resume 续采）")
    return 0


# ── 4. 列表整页扫描（仅名称/等级）────────────────────────
def auto_pages(game: str, window_title: str, pages: int, output: str,
               fail_safe: bool = False) -> int:
    pyautogui = _need("pyautogui")
    pyautogui.FAILSAFE = fail_safe
    from PIL import ImageGrab
    strat = CLICK_STRATEGIES.get(game, CLICK_STRATEGIES["genshin"])
    win = _find_window(window_title)
    collected: list[str] = []
    for page in range(1, pages + 1):
        img = ImageGrab.grab(bbox=(win.left, win.top,
                                   win.left + win.width, win.top + win.height))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        items = ocr_screen(buf.getvalue())
        collected.extend(t[2] for t in items)
        pyautogui.press(strat["page"])
        time.sleep(strat["wait_list"])
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"game": game, "raw_lines": collected}, f,
                  ensure_ascii=False, indent=2)
    print(f"完成：{len(collected)} 行 → {output}")
    return 0


# ── 5. 离线测试 ────────────────────────────────────────
def from_text_file(path: str, output: str) -> int:
    lines = [ln.strip() for ln in open(path, encoding="utf-8") if ln.strip()]
    cards = parse_cards(lines)
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"game": "genshin", "characters": [], "weapons": [],
                   "artifacts": cards, "materials": []}, f,
                  ensure_ascii=False, indent=2)
    print(f"解析 {len(cards)} 条 → {output}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="二游毕业指导 · 伴生自动导出器（自动点击详情+OCR）")
    ap.add_argument("--text-lines", default=None, help="离线测试：从文本文件解析")
    ap.add_argument("--pages", type=int, default=0, help="列表整页扫描页数")
    ap.add_argument("--auto-detail", action="store_true",
                    help="自动点击详情采集（推荐，完整属性）；中断后可用 --resume 续采")
    ap.add_argument("--game", default="genshin", help="genshin / wuthering / zzz")
    ap.add_argument("--window", default="", help="游戏窗口标题（如 原神 / 绝区零）")
    ap.add_argument("--output", default="artifacts.json", help="导出文件路径")
    ap.add_argument("--max-items", type=int, default=200, help="自动点击最多采集件数")
    ap.add_argument("--resume", action="store_true",
                    help="从 <output>.state.json 断点续采（跳过已采件数，保留已采数据）")
    ap.add_argument("--max-miss", type=int, default=10,
                    help="连续识别失败 N 件即停止（防卡死/防越界，默认 10）")
    ap.add_argument("--viewport", default=None,
                    help="游戏画面在窗口内的百分比区域 x,y,w,h（如 0,12,100,82；浏览器/云游戏非全屏时用）")
    ap.add_argument("--fail-safe", action="store_true",
                    help="启用 pyautogui fail-safe（鼠标到屏幕左上角即紧急停止；默认关闭防误触）")
    ap.add_argument("--calibrate", action="store_true", help="打印窗口与点击策略，用于校准坐标")
    args = ap.parse_args()

    if args.text_lines:
        raise SystemExit(from_text_file(args.text_lines, args.output))
    if args.auto_detail or args.pages or args.calibrate:
        title = args.window or {"genshin": "原神", "wuthering": "鸣潮", "zzz": "绝区零"}[args.game]
        if args.auto_detail or args.calibrate:
            raise SystemExit(auto_detail(args.game, title, args.output,
                                         args.max_items, args.calibrate,
                                         args.resume, args.max_miss,
                                         args.viewport, args.fail_safe))
        raise SystemExit(auto_pages(args.game, title, args.pages, args.output,
                                    args.fail_safe))
    print(ap.format_help())


if __name__ == "__main__":
    main()
