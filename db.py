import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from config import SQLITE_DB_PATH, LIMIT_PER_USER

WIB = timezone(timedelta(hours=7))


def _conn():
    path = SQLITE_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS gtc_session (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            token TEXT NOT NULL,
            device_json TEXT NOT NULL,
            phone TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_blocked INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS usage_weekly (
            telegram_id TEXT NOT NULL,
            week_key TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (telegram_id, week_key)
        );

        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL,
            phone_masked TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_search_logs_created_at
        ON search_logs(created_at);

        CREATE TABLE IF NOT EXISTS admin_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        conn.commit()
    print(f"✅ SQLite ready -> {SQLITE_DB_PATH}")


def _now():
    return datetime.now(WIB)


def _week_key():
    now = _now()
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


def touch_user(user):
    now = _now().isoformat()
    uid = str(user.id)
    username = user.username or ""
    first_name = user.first_name or ""
    with _conn() as conn:
        row = conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (uid,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, last_seen=? WHERE telegram_id=?",
                (username, first_name, now, uid),
            )
        else:
            conn.execute(
                "INSERT INTO users(telegram_id,username,first_name,first_seen,last_seen) VALUES(?,?,?,?,?)",
                (uid, username, first_name, now, now),
            )
        conn.commit()


def is_blocked(telegram_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT is_blocked FROM users WHERE telegram_id=?",
            (str(telegram_id),),
        ).fetchone()
    return bool(row and row["is_blocked"])


def set_blocked(telegram_id, blocked=True):
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET is_blocked=? WHERE telegram_id=?",
            (1 if blocked else 0, str(telegram_id)),
        )
        conn.commit()


def get_user_usage(telegram_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT used FROM usage_weekly WHERE telegram_id=? AND week_key=?",
            (str(telegram_id), _week_key()),
        ).fetchone()
    return int(row["used"]) if row else 0


def increment_usage(telegram_id):
    uid = str(telegram_id)
    wk = _week_key()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO usage_weekly(telegram_id, week_key, used)
            VALUES(?,?,1)
            ON CONFLICT(telegram_id, week_key)
            DO UPDATE SET used = used + 1
            """,
            (uid, wk),
        )
        conn.commit()


def get_remaining(telegram_id):
    return max(0, LIMIT_PER_USER - get_user_usage(telegram_id))


def reset_user_usage(telegram_id):
    with _conn() as conn:
        conn.execute(
            "DELETE FROM usage_weekly WHERE telegram_id=? AND week_key=?",
            (str(telegram_id), _week_key()),
        )
        conn.commit()


def get_week_reset_info():
    now = _now()
    days = 7 - now.weekday()
    next_monday = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return next_monday, max(1, (next_monday.date() - now.date()).days)


def _mask_phone(phone):
    d = "".join(ch for ch in phone if ch.isdigit())
    if len(d) <= 6:
        return "*" * len(d)
    return d[:4] + "*" * (len(d) - 8) + d[-4:]


def log_search(telegram_id, phone, status):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO search_logs(telegram_id,phone_masked,status,created_at) VALUES(?,?,?,?)",
            (str(telegram_id), _mask_phone(phone), status, _now().isoformat()),
        )
        conn.commit()


def save_session(token, device, phone):
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO gtc_session(id,token,device_json,phone,updated_at)
            VALUES(1,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                token=excluded.token,
                device_json=excluded.device_json,
                phone=excluded.phone,
                updated_at=excluded.updated_at
            """,
            (token, json.dumps(device), phone, _now().isoformat()),
        )
        conn.commit()


def load_session():
    with _conn() as conn:
        row = conn.execute("SELECT token,device_json,phone FROM gtc_session WHERE id=1").fetchone()
    if not row:
        return None
    return {
        "token": row["token"],
        "device": json.loads(row["device_json"]),
        "phone": row["phone"],
    }


def clear_session():
    with _conn() as conn:
        conn.execute("DELETE FROM gtc_session WHERE id=1")
        conn.commit()


def log_admin(admin_id, action):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO admin_actions(admin_id,action,created_at) VALUES(?,?,?)",
            (str(admin_id), action, _now().isoformat()),
        )
        conn.commit()


def dashboard_stats():
    now = _now()
    today = now.date().isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    with _conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        active_today = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE substr(last_seen,1,10)=?", (today,)
        ).fetchone()["c"]
        searches_today = conn.execute(
            "SELECT COUNT(*) c FROM search_logs WHERE substr(created_at,1,10)=?", (today,)
        ).fetchone()["c"]
        searches_7d = conn.execute(
            "SELECT COUNT(*) c FROM search_logs WHERE created_at>=?", (week_ago,)
        ).fetchone()["c"]
        success_today = conn.execute(
            "SELECT COUNT(*) c FROM search_logs WHERE substr(created_at,1,10)=? AND status='success'",
            (today,),
        ).fetchone()["c"]
        blocked = conn.execute("SELECT COUNT(*) c FROM users WHERE is_blocked=1").fetchone()["c"]
    return {
        "total_users": total_users,
        "active_today": active_today,
        "searches_today": searches_today,
        "searches_7d": searches_7d,
        "success_today": success_today,
        "blocked": blocked,
    }


def top_users(limit=5):
    wk = _week_key()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT u.telegram_id,u.username,u.first_name,w.used
            FROM usage_weekly w
            LEFT JOIN users u ON u.telegram_id=w.telegram_id
            WHERE w.week_key=?
            ORDER BY w.used DESC
            LIMIT ?
            """,
            (wk, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_searches(limit=8):
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.telegram_id,s.phone_masked,s.status,s.created_at,u.username,u.first_name
            FROM search_logs s
            LEFT JOIN users u ON u.telegram_id=s.telegram_id
            ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
