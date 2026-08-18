"""轻量存储层：stdlib sqlite3，零第三方依赖。

表结构与《二游毕业指导.md》§4 对应；默认 SQLite，生产可换 MySQL（SQL 基本兼容）。
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS game (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT,
  weapon_name TEXT, equipment_name TEXT, adapter_key TEXT,
  max_team_size INTEGER DEFAULT 4
);
CREATE TABLE IF NOT EXISTS entity (
  id INTEGER PRIMARY KEY, game_id INTEGER, type TEXT, name TEXT,
  aliases TEXT, rarity INTEGER, max_level INTEGER, attrs TEXT
);
CREATE TABLE IF NOT EXISTS kb_build (
  id INTEGER PRIMARY KEY, game_id INTEGER, char_id INTEGER, weapon_ids TEXT,
  artifact_ids TEXT, main_stats TEXT, substat_priority TEXT,
  version TEXT, source TEXT, review_status TEXT
);
CREATE TABLE IF NOT EXISTS kb_graduation (
  id INTEGER PRIMARY KEY, game_id INTEGER, char_id INTEGER, criteria TEXT,
  version TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS kb_recipe (
  id INTEGER PRIMARY KEY, game_id INTEGER, entity_id INTEGER,
  kind TEXT, recipe TEXT
);
CREATE TABLE IF NOT EXISTS kb_weapon (
  entity_id INTEGER PRIMARY KEY, game_id INTEGER,
  weapon_type TEXT, base_atk INTEGER, main_stat TEXT,
  main_stat_value REAL, passive TEXT
);
CREATE TABLE IF NOT EXISTS kb_team (
  id INTEGER PRIMARY KEY, game_id INTEGER, name TEXT, member_ids TEXT,
  synergy TEXT, version TEXT
);
CREATE TABLE IF NOT EXISTS user_standard (
  id INTEGER PRIMARY KEY, user_id TEXT, game_id INTEGER, char_id INTEGER,
  tier TEXT, overrides TEXT, version TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS user_feedback (
  id INTEGER PRIMARY KEY, session_id TEXT, target_type TEXT, target_id INTEGER,
  action TEXT, correction TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS user_asset (
  id INTEGER PRIMARY KEY, session_id TEXT, game_id INTEGER, type TEXT DEFAULT '材料',
  entity_id INTEGER, level INTEGER, rarity INTEGER, slot TEXT, stats TEXT, raw_text TEXT,
  conf REAL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS team_graduate (
  id INTEGER PRIMARY KEY, session_id TEXT, game_id INTEGER, member_ids TEXT,
  member_weights TEXT, score REAL, per_member TEXT, assignment TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ocr_sample (
  id INTEGER PRIMARY KEY, game_id INTEGER, image_path TEXT, texts TEXT,
  entities TEXT, reviewed INTEGER DEFAULT 0, created_at TEXT
);
"""


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DROP_SCHEMA = """
DROP TABLE IF EXISTS user_feedback;
DROP TABLE IF EXISTS team_graduate;
DROP TABLE IF EXISTS user_standard;
DROP TABLE IF EXISTS user_asset;
DROP TABLE IF EXISTS ocr_sample;
DROP TABLE IF EXISTS kb_weapon;
DROP TABLE IF EXISTS kb_recipe;
DROP TABLE IF EXISTS kb_team;
DROP TABLE IF EXISTS kb_graduation;
DROP TABLE IF EXISTS kb_build;
DROP TABLE IF EXISTS entity;
DROP TABLE IF EXISTS game;
"""


def init_db() -> None:
    with closing(_conn()) as c, c:
        c.executescript(SCHEMA)
        # 旧库结构升级：缺 weapon_name / max_team_size 列则重建（开发阶段）
        cols = [r["name"] for r in c.execute("PRAGMA table_info(game)")]
        if cols and ("weapon_name" not in cols or "max_team_size" not in cols):
            c.executescript(DROP_SCHEMA)
            c.executescript(SCHEMA)
        # user_asset 增量迁移：加 type 列（角色/武器/装备/材料分开保存，幂等，不重建用户数据）
        acols = [r["name"] for r in c.execute("PRAGMA table_info(user_asset)")]
        if "type" not in acols:
            c.execute("ALTER TABLE user_asset ADD COLUMN type TEXT DEFAULT '材料'")
            # 旧数据按 entity 反查补 type（角色/武器/装备），无法反查的归为材料
            c.execute(
                "UPDATE user_asset SET type = COALESCE("
                "(SELECT e.type FROM entity e WHERE e.id = user_asset.entity_id), '材料')")


def query(sql: str, params=()) -> list[dict]:
    with closing(_conn()) as c, c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def query_one(sql: str, params=()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=()) -> int:
    with closing(_conn()) as c, c:
        cur = c.execute(sql, params)
        return cur.lastrowid
