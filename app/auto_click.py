"""伴生工具自动点击 · 网页接入（subprocess 启动 auto_export.py + 状态/日志/停止）。

合规边界：仅在用户自己的电脑上运行（单机 localhost 服务）；参数白名单校验；
输出路径限定在项目目录内；不注入、不修改游戏文件（工具本体只读截图+模拟点击详情/返回）。

用法（前端调用）：
  POST /api/v1/auto-click/start   启动（参数见 AutoClickReq）
  GET  /api/v1/auto-click/status  查询进度/状态
  POST /api/v1/auto-click/stop    终止（断点已落盘，可 --resume 续采）
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTO_SCRIPT = BASE_DIR / "tools" / "auto_export.py"
LOG_DIR = BASE_DIR / "data"
LOG_FILE = LOG_DIR / "auto_click.log"

GAMES = {"genshin", "wuthering", "zzz"}
WINDOW_DEFAULT = {"genshin": "原神", "wuthering": "鸣潮", "zzz": "绝区零"}

# 运行状态（单实例：同时只允许一个采集任务）
_state: dict = {"proc": None, "output": "", "game": "", "started_at": 0}


def _proc() -> subprocess.Popen | None:
    return _state.get("proc")


def _log_tail(n: int = 40) -> list[str]:
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:      # 兼容旧日志（Windows 子进程曾按 GBK 写）
        text = LOG_FILE.read_text(encoding="gbk", errors="replace")
    except FileNotFoundError:
        return []
    return text.splitlines()[-n:]


def _running() -> bool:
    p = _proc()
    return p is not None and p.poll() is None


def start(game: str, window: str = "", output: str = "data/artifacts_auto.json",
          max_items: int = 200, resume: bool = False, max_miss: int = 10,
          viewport: str | None = None) -> dict:
    """启动 auto_export.py --auto-detail（参数白名单 + 路径限定）。"""
    if _running():
        raise ValueError("已有采集任务在运行，请先停止再启动")
    if game not in GAMES:
        raise ValueError(f"未知游戏: {game}（可选 {'/'.join(sorted(GAMES))}）")
    if not (1 <= int(max_items) <= 2000):
        raise ValueError("max_items 需在 1~2000 之间")
    if not (1 <= int(max_miss) <= 100):
        raise ValueError("max_miss 需在 1~100 之间")
    if viewport:
        try:
            parts = [float(x) for x in viewport.replace("，", ",").split(",")]
        except ValueError:
            raise ValueError("viewport 需为 x,y,w,h 四个 0~100 百分比（如 0,12,100,82）")
        if len(parts) != 4 or not all(0 <= p <= 100 for p in parts) or parts[2] == 0 or parts[3] == 0:
            raise ValueError("viewport 需为 x,y,w,h 四个 0~100 百分比（宽高大于 0）")
    out = Path(output)
    if not out.is_absolute():
        out = BASE_DIR / out
    out = out.resolve()
    if not str(out).startswith(str(BASE_DIR.resolve())):
        raise ValueError("输出路径必须在项目目录内")
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, str(AUTO_SCRIPT), "--auto-detail",
           "--game", game,
           "--window", window or WINDOW_DEFAULT[game],
           "--output", str(out),
           "--max-items", str(int(max_items)),
           "--max-miss", str(int(max_miss))]
    if viewport:
        cmd += ["--viewport", viewport]
    if resume:
        cmd.append("--resume")
    LOG_DIR.mkdir(exist_ok=True)
    log_f = open(LOG_FILE, "w", encoding="utf-8")     # 新任务重写日志，便于状态解析
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"   # 子进程 print 统一写 UTF-8，避免 Windows GBK 乱码
    proc = subprocess.Popen(
        cmd, cwd=str(BASE_DIR), env=env, stdout=log_f, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _state.update(proc=proc, output=str(out), game=game, started_at=time.time())
    return {"started": True, "game": game, "output": str(out),
            "pid": proc.pid, "resume": bool(resume)}


def status() -> dict:
    """运行状态 + 日志尾部 + 进度/已收集件数解析。"""
    p = _proc()
    if p is None:
        return {"running": False, "output": _state.get("output", ""), "started": False,
                "progress": None, "collected": None, "log": []}
    running = p.poll() is None
    tail = _log_tail(40)
    progress = None
    collected = None
    for ln in reversed(tail):
        m = re.search(r"进度\s*(\d+)/(\d+)", ln)
        if m and progress is None:
            progress = {"current": int(m.group(1)), "total": int(m.group(2))}
        m2 = re.search(r"已收集\s*(\d+)\s*条", ln)
        if m2 and collected is None:
            collected = int(m2.group(1))
    done = any(("完成：" in ln or "停止采集" in ln or "Traceback" in ln
                or "未找到游戏窗口" in ln or "缺少依赖" in ln)
               for ln in tail)
    error = next((ln for ln in tail
                  if "Traceback" in ln or "未找到游戏窗口" in ln
                  or "缺少依赖" in ln or "Error" in ln), None)
    return {
        "running": running,
        "started": True,
        "output": _state.get("output", ""),
        "game": _state.get("game", ""),
        "pid": p.pid,
        "exit_code": None if running else p.poll(),
        "progress": progress,
        "collected": collected,
        "done": done,
        "error": error,
        "log": tail,
    }


def stop() -> dict:
    """终止采集（工具每件落盘断点，之后可用 --resume / 网页续采）。"""
    p = _proc()
    if p is None or p.poll() is not None:
        return {"stopped": False, "reason": "没有运行中的采集任务"}
    p.terminate()
    return {"stopped": True, "pid": p.pid}
