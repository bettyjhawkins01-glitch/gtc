"""
db.py — SQLite storage (no PostgreSQL required)

Recommended on Railway:
- Add a Volume mounted at /data
- Optional variable: SQLITE_DB_PATH=/data/bot.db

Without a Volume, Railway's local filesystem may be reset on redeploy/restart.
"""

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from config import LIMIT_PER_USER


def _db_path() -> str:
    path = (os.getenv("SQLITE_DB_PATH") or "/data/bot.db").strip()
    parent = Path(path).parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        # Local/dev fallback when /data is unavailable.
        fallback = "/tmp/bot.db"
        Path(fallback).parent.mkdir(parents=True, exist_ok=True)
        return fallback


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_usage (
                user_id    TEXT NOT NULL,
                week_start TEXT NOT NULL,
                usage      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, week_start)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gtc_session (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                token      TEXT,
                phone      TEXT,
                device     TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT OR IGNORE INTO gtc_session (id) VALUES (1)")
        conn.commit()
    print(f"SQLite ready -> {_db_path()}")


def get_user_usage(user_id: str) -> int:
    ws = _week_start().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT usage FROM user_usage WHERE user_id = ? AND week_start = ?",
            (str(user_id), ws),
        ).fetchone()
        return int(row["usage"]) if row else 0


def increment_usage(user_id: str):
    ws = _week_start().isoformat()
    with _conn() as conn:
        conn.execute("""
            INSERT INTO user_usage (user_id, week_start, usage)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, week_start)
            DO UPDATE SET usage = usage + 1
        """, (str(user_id), ws))
        conn.commit()


def get_remaining(user_id: str) -> int:
    return max(0, LIMIT_PER_USER - get_user_usage(user_id))


def get_week_reset_info() -> tuple:
    ws = _week_start()
    next_monday = ws + timedelta(days=7)
    days_left = (next_monday - date.today()).days
    return next_monday, days_left


def reset_user(user_id: str):
    with _conn() as conn:
        conn.execute("DELETE FROM user_usage WHERE user_id = ?", (str(user_id),))
        conn.commit()


def get_all_users() -> dict:
    ws = _week_start().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT user_id, usage FROM user_usage WHERE week_start = ? ORDER BY usage DESC",
            (ws,),
        ).fetchall()
        return {row["user_id"]: int(row["usage"]) for row in rows}


def save_session(token: str, device: dict, phone: str):
    with _conn() as conn:
        conn.execute("""
            UPDATE gtc_session
            SET token = ?, phone = ?, device = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (token, phone, json.dumps(device)))
        conn.commit()


def load_session() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT token, phone, device FROM gtc_session WHERE id = 1"
        ).fetchone()
        if not row or not row["token"]:
            return None

        device = row["device"]
        if device:
            try:
                device = json.loads(device)
            except (TypeError, json.JSONDecodeError):
                device = {}
        else:
            device = {}

        return {
            "token": row["token"],
            "phone": row["phone"],
            "device": device,
        }


def clear_session():
    with _conn() as conn:
        conn.execute("""
            UPDATE gtc_session
            SET token = NULL, phone = NULL, device = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """)
        conn.commit()
