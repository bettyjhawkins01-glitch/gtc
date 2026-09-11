import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
GTC_PHONE = os.environ["GTC_PHONE"]
LIMIT_PER_USER = int(os.getenv("LIMIT_PER_USER", "3"))

# SQLite path for Railway persistent volume.
# If SQLITE_DB_PATH is not set, fall back to local bot.db.
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/bot.db")
