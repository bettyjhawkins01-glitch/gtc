# ─────────────────────────────────────────────
#  Konfigurasi Bot — semua dari ENV VARIABLE
#  Isi di Railway Dashboard → Variables
# ─────────────────────────────────────────────

import os

# Token Bot Telegram (dari @BotFather)
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Nomor HP akun GetContact (tanpa +), contoh: 628123456789
GTC_PHONE = os.environ["GTC_PHONE"]

# Batas pencarian per user (default 3)
LIMIT_PER_USER = int(os.environ.get("LIMIT_PER_USER", "3"))

# PostgreSQL URL dari Railway (otomatis di-set Railway)
DATABASE_URL = os.environ["DATABASE_URL"]
