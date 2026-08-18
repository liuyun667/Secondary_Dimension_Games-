"""全局配置：DB 路径、组件开关、LLM 端点。

核心引擎零第三方依赖；重型组件（PaddleOCR/fasttext/sklearn/LLM）通过环境变量按需启用。
支持 `.env` 配置文件（项目根目录）：启动时自动加载，环境变量优先于 `.env`。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载（零依赖）：KEY=VALUE 逐行读入，已存在的环境变量不被覆盖。"""
    p = path or (BASE_DIR / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

# 存储
DB_PATH = os.environ.get("GYZ_DB_PATH", str(BASE_DIR / "data" / "gyz.db"))

# 组件开关
SIMULATE_OCR = os.environ.get("GYZ_SIMULATE_OCR", "1") == "1"
USE_FASTTEXT = os.environ.get("GYZ_USE_FASTTEXT", "0") == "1"
# fasttext C++ 底层在 Windows 上无法写入非 ASCII 路径，故默认存到用户主目录 ASCII 路径
FASTTEXT_MODEL = os.environ.get(
    "GYZ_FASTTEXT_MODEL", str(Path.home() / ".gyz_models" / "classifier.bin"))
USE_RF = os.environ.get("GYZ_USE_RF", "0") == "1"

# LLM（可选）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("GYZ_LLM_MODEL", "deepseek-chat")
