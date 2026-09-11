import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
GTC_PHONE = os.environ["GTC_PHONE"].lstrip("+")
LIMIT_PER_USER = int(os.getenv("LIMIT_PER_USER", "3"))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/bot.db")

# Telegram numeric user IDs, comma-separated. Example: 123456789,987654321
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
