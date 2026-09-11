"""
db.py — PostgreSQL database via psycopg2 (Railway-safe)
Tabel: user_usage   → limit pencarian per minggu per Telegram user
Tabel: gtc_session  → token + device GTC
"""

import json
import os
from datetime import date, timedelta
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

from config import LIMIT_PER_USER


def _database_url() -> str:
    """Ambil koneksi PostgreSQL dari Railway dengan fallback aman."""
    url = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL") or "").strip()
    if url:
        return url

    # Fallback kalau user memilih mereferensikan PG* satu per satu di Railway.
    host = (os.getenv("PGHOST") or "").strip()
    port = (os.getenv("PGPORT") or "5432").strip()
    user = (os.getenv("PGUSER") or "").strip()
    password = os.getenv("PGPASSWORD") or ""
    dbname = (os.getenv("PGDATABASE") or "").strip()

    if host and user and dbname:
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    raise RuntimeError(
        "DATABASE_URL kosong di runtime Railway. "
        "Set DATABASE_URL sebagai reference ke ${{Postgres.DATABASE_URL}} "
        "dan pastikan staged changes sudah di-deploy."
    )


def _conn():
    url = _database_url()

    # Log aman: hanya host/database, tanpa username/password.
    parsed = urlparse(url)
    host = parsed.hostname or "(unknown)"
    dbname = (parsed.path or "").lstrip("/") or "(unknown)"
    print(f"DB connect -> host={host}, db={dbname}")

    # Railway Postgres mendukung SSL. connect_timeout mencegah bot menggantung lama.
    return psycopg2.connect(url, sslmode="require", connect_timeout=10)


def _week_start() -> date:
    """Senin minggu ini (Senin = hari pertama minggu ISO)."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def init_db():
    """Buat tabel jika belum ada. Dipanggil saat bot start."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_usage (
                    user_id    TEXT NOT NULL,
                    week_start DATE NOT NULL,
                    usage      INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, week_start)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gtc_session (
                    id         INTEGER PRIMARY KEY DEFAULT 1,
                    token      TEXT,
                    phone      TEXT,
                    device     JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    CHECK (id = 1)
                )
            """)
            cur.execute("""
                INSERT INTO gtc_session (id) VALUES (1)
                ON CONFLICT (id) DO NOTHING
            """)
        conn.commit()


def get_user_usage(user_id: str) -> int:
    ws = _week_start()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT usage FROM user_usage WHERE user_id = %s AND week_start = %s",
                (user_id, ws),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def increment_usage(user_id: str):
    ws = _week_start()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_usage (user_id, week_start, usage) VALUES (%s, %s, 1)
                ON CONFLICT (user_id, week_start) DO UPDATE
                    SET usage = user_usage.usage + 1
            """, (user_id, ws))
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
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_usage WHERE user_id = %s", (user_id,))
        conn.commit()


def get_all_users() -> dict:
    ws = _week_start()
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, usage FROM user_usage WHERE week_start = %s ORDER BY usage DESC",
                (ws,),
            )
            return {row["user_id"]: row["usage"] for row in cur.fetchall()}


def save_session(token: str, device: dict, phone: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE gtc_session
                SET token = %s, phone = %s, device = %s, updated_at = NOW()
                WHERE id = 1
            """, (token, phone, json.dumps(device)))
        conn.commit()


def load_session() -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT token, phone, device FROM gtc_session WHERE id = 1")
            row = cur.fetchone()
            if not row or not row["token"]:
                return None
            return {
                "token": row["token"],
                "phone": row["phone"],
                "device": row["device"],
            }


def clear_session():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE gtc_session
                SET token = NULL, phone = NULL, device = NULL, updated_at = NOW()
                WHERE id = 1
            """)
        conn.commit()
