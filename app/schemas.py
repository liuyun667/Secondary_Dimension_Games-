"""Pydantic 请求/响应模型（FastAPI 层）。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class AnalyzeReq(BaseModel):
    game_id: int
    image: Optional[str] = None          # base64 图片（可选）
    text_lines: Optional[list[str]] = None  # OCR 模拟/已提取文本行
    session_id: str = "session-demo"


class GraduateReq(BaseModel):
    game_id: int
    character_id: int
    assets: list[dict[str, Any]]
    user_id: Optional[str] = None
    standard: Optional[dict[str, Any]] = None   # {tier?, overrides?}


class RecommendReq(BaseModel):
    game_id: int
    character_id: int
    assets: list[dict[str, Any]]
    user_id: Optional[str] = None


class StandardsReq(BaseModel):
    user_id: str
    game_id: int
    character_id: int
    tier: str = "standard"                       # casual/standard/extreme/custom
    overrides: dict[str, Any] = {}


class TeamReq(BaseModel):
    game_id: int
    members: list[int]                           # 角色实体 id
    assets: list[dict[str, Any]]
    weights: Optional[dict[str, float]] = None   # 成员名 → 权重
    session_id: str = "session-demo"


class FeedbackReq(BaseModel):
    session_id: str
    target_type: str                             # recommend/graduate/team
    target_id: int
    action: str                                  # 采纳/拒绝/纠正
    correction: Optional[dict[str, Any]] = None


class AssetsSaveReq(BaseModel):
    user_id: str
    game_id: int
    assets: list[dict[str, Any]]


class CollectReq(BaseModel):
    game_id: int
    method: str                          # file / clipboard / sample / ocr
    payload: Optional[dict[str, Any]] = None


class RecommendBatchReq(BaseModel):
    game_id: int
    character_ids: list[int]                     # 1~9 人
    assets: list[dict[str, Any]]
    user_id: Optional[str] = None


class TeamItem(BaseModel):
    members: list[int]                           # 2~4 人
    weights: Optional[dict[str, float]] = None


class TeamsReq(BaseModel):
    game_id: int
    teams: list[TeamItem]                        # 1~4 队
    assets: list[dict[str, Any]]
    session_id: str = "session-demo"


class AdviceReq(BaseModel):
    game_id: int
    character_ids: list[int]                     # 1~9 人
    assets: list[dict[str, Any]]
    user_id: Optional[str] = None
    tier: str = "standard"                       # casual/standard/extreme（毕业档位）


class AutoClickReq(BaseModel):
    game: str                                    # genshin / wuthering / zzz
    window: str = ""                             # 游戏窗口标题（留空用默认）
    output: str = "data/artifacts_auto.json"     # 输出文件（项目目录内）
    max_items: int = 200
    resume: bool = False                         # 断点续采
    max_miss: int = 10                           # 连续识别失败 N 件停止
    viewport: Optional[str] = None               # 游戏画面在窗口内的百分比区域 x,y,w,h（浏览器/云游戏用）


class TestDataReq(BaseModel):
    session: str = "test_demo"                   # 测试账户标识
    game_id: int = 1                             # 游戏 id（1=原神）
