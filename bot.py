"""
bot.py — Bot Telegram GetContact (Railway-ready)
"""

import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler,
    ConversationHandler,
)

from config import BOT_TOKEN, GTC_PHONE, LIMIT_PER_USER
from db import init_db, get_user_usage, increment_usage, get_remaining, get_week_reset_info
from gtc_auth import gtc, clear_session

WAIT_OTP = 1

# ─────────────────────────────────────────────
#  Startup
# ─────────────────────────────────────────────

async def post_init(application):
    init_db()  # buat tabel jika belum ada
    if gtc.restore_session():
        print(f"✅ Session restored — token: {gtc.token[:20]}...")
    else:
        print("⚠️  Belum ada session. Gunakan /login di bot.")

# ─────────────────────────────────────────────
#  Format hasil
# ─────────────────────────────────────────────

def format_result(data: dict, phone: str) -> str:
    if data.get("error"):
        msg = data.get("message") or data.get("raw") or "Unknown error"
        return f"❌ *Gagal mengambil data*\n`{msg}`"

    result   = data.get("result", {})
    profiles = result.get("profiles", [])
    tags     = result.get("tags", [])
    spam     = result.get("spamInfo", {})

    lines = [f"📱 *Hasil GetContact*\n🔢 Nomor: `{phone}`\n"]

    if profiles:
        lines.append(f"👤 *Nama tersimpan ({len(profiles)} orang):*")
        for i, p in enumerate(profiles[:15], 1):
            lines.append(f"  `{i}.` {p.get('name','—')}")
        if len(profiles) > 15:
            lines.append(f"  _...+{len(profiles)-15} nama lainnya_")
    else:
        lines.append("👤 Tidak ada nama ditemukan")

    lines.append("")
    if tags:
        tag_texts = [t.get("tag","") for t in tags if t.get("tag")]
        if tag_texts:
            lines.append(f"🏷 *Tag:* `{', '.join(tag_texts)}`")

    if spam:
        count = spam.get("count", 0)
        stype = spam.get("type", "")
        if count > 0:
            lines.append(f"⚠️ *Spam:* {count}x" + (f" ({stype})" if stype else ""))
        else:
            lines.append("✅ Tidak ada laporan spam")

    lines.append(f"\n🕐 `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`")
    return "\n".join(lines)

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user      = update.effective_user
    remaining = get_remaining(str(user.id))
    logged_in = gtc.token is not None

    si = "🟢" if logged_in else "🔴"
    st = "Terhubung ke GetContact" if logged_in else "Belum login — ketik /login"

    text = (
        f"👋 Halo *{user.first_name}*!\n\n"
        f"{si} *Status:* {st}\n\n"
        f"🔍 Kirim nomor HP untuk dicek\n"
        f"Format: `+628xxxxxxxxxx`\n\n"
        f"⚡ *Sisa kuota minggu ini:* `{remaining}/{LIMIT_PER_USER}`\n"
        f"🔄 Reset tiap Senin pagi"
    )
    kb = [[
        InlineKeyboardButton("📊 Cek Kuota", callback_data="kuota"),
        InlineKeyboardButton("❓ Bantuan",   callback_data="help"),
    ]]
    if not logged_in:
        kb.insert(0, [InlineKeyboardButton("🔐 Login GetContact", callback_data="do_login")])

    await update.message.reply_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))

# ─────────────────────────────────────────────
#  /login — ConversationHandler
# ─────────────────────────────────────────────

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🔐 *Memulai login GetContact...*\n\n"
        "⚙️ Generating device fingerprint random...",
        parse_mode="Markdown"
    )
    try:
        await gtc.register_device()
        dev = gtc.device
        await msg.edit_text(
            f"✅ *Device di-generate!*\n\n"
            f"📱 `{dev['brand']} {dev['model']}`\n"
            f"🤖 Android `{dev['android_version']}`\n"
            f"🔑 ID: `{dev['device_id'][:18]}...`\n\n"
            f"📤 Mengirim OTP ke `+{GTC_PHONE}`...",
            parse_mode="Markdown"
        )

        otp_resp = await gtc.send_otp(GTC_PHONE)
        if otp_resp.get("error") or otp_resp.get("status", 200) >= 400:
            err = otp_resp.get("message") or otp_resp.get("raw") or str(otp_resp)
            await msg.edit_text(f"❌ *Gagal kirim OTP*\n\n`{err}`\n\nCoba /login lagi.",
                                parse_mode="Markdown")
            return ConversationHandler.END

        await msg.edit_text(
            f"📲 *OTP dikirim ke* `+{GTC_PHONE}`\n\n"
            f"Ketik 6 digit kode OTP yang kamu terima:",
            parse_mode="Markdown"
        )
        return WAIT_OTP

    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END


async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    if not otp.isdigit() or len(otp) < 4:
        await update.message.reply_text("⚠️ OTP tidak valid. Masukkan kode angka dari SMS.")
        return WAIT_OTP

    msg = await update.message.reply_text("🔄 *Memverifikasi OTP...*", parse_mode="Markdown")
    try:
        result = await gtc.verify_otp(otp)
        if gtc.token:
            await msg.edit_text(
                f"✅ *Login berhasil!*\n\n"
                f"🔑 Token: `{gtc.token[:25]}...`\n\n"
                f"Kirim nomor HP untuk mulai mencari!",
                parse_mode="Markdown"
            )
        else:
            err = result.get("message") or result.get("raw") or str(result)
            await msg.edit_text(
                f"❌ *OTP salah / expired*\n\n`{err}`\n\nCoba /login lagi.",
                parse_mode="Markdown"
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")

    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Login dibatalkan.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
#  /logout
# ─────────────────────────────────────────────

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_session()
    await update.message.reply_text(
        "🔓 *Session dihapus.*\n\nGunakan /login untuk login ulang.",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if gtc.token:
        dev = gtc.device or {}
        text = (
            f"🟢 *Status: Login*\n\n"
            f"📱 `{dev.get('brand','-')} {dev.get('model','-')}`\n"
            f"🤖 Android `{dev.get('android_version','-')}`\n"
            f"📞 `+{gtc.phone or '-'}`\n"
            f"🔑 `{gtc.token[:30]}...`"
        )
    else:
        text = "🔴 *Belum Login*\n\nGunakan /login untuk masuk."
    await update.message.reply_text(text, parse_mode="Markdown")

# ─────────────────────────────────────────────
#  /cek
# ─────────────────────────────────────────────

async def cek_kuota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user      = update.effective_user
    used      = get_user_usage(str(user.id))
    remaining = get_remaining(str(user.id))
    bar       = "🟩" * remaining + "⬜" * (LIMIT_PER_USER - remaining)
    next_reset, days_left = get_week_reset_info()
    reset_str = f"{next_reset.strftime('%d %b %Y')} ({days_left} hari lagi)"
    text = (
        f"📊 *Status Kuota Minggu Ini*\n\n"
        f"👤 {user.first_name}\n"
        f"{bar}\n"
        f"Sudah pakai: `{used}/{LIMIT_PER_USER}`\n"
        f"Sisa: `{remaining}/{LIMIT_PER_USER}`\n"
        f"🔄 Reset: `{reset_str}`\n\n"
        + ("🟢 Masih bisa mencari!" if remaining > 0 else "❌ Kuota habis minggu ini!\nTunggu reset Senin depan.")
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─────────────────────────────────────────────
#  Handler nomor HP
# ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text    = update.message.text.strip()

    phone  = text if text.startswith("+") else f"+{text}"
    digits = phone[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        await update.message.reply_text(
            "⚠️ Format tidak valid.\nContoh: `+628123456789`",
            parse_mode="Markdown"
        )
        return

    if not gtc.token:
        await update.message.reply_text(
            "🔴 *Belum login!*\n\nGunakan /login dulu.",
            parse_mode="Markdown"
        )
        return

    if get_remaining(user_id) <= 0:
        _, days_left = get_week_reset_info()
        await update.message.reply_text(
            f"❌ *Kuota minggu ini habis!*\n\n"
            f"Limit `{LIMIT_PER_USER}x` per minggu sudah terpakai.\n"
            f"🔄 Reset otomatis *{days_left} hari lagi* (Senin depan).",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🔍 Mencari data...")
    try:
        increment_usage(user_id)
        remaining = get_remaining(user_id)
        data      = await gtc.search(phone)
        result    = format_result(data, phone)
        result   += f"\n\n📦 *Sisa kuota minggu ini:* `{remaining}/{LIMIT_PER_USER}`"
        await msg.edit_text(result, parse_mode="Markdown")
    except asyncio.TimeoutError:
        await msg.edit_text("⏱ Timeout! Coba lagi nanti.", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")

# ─────────────────────────────────────────────
#  Callback inline buttons
# ─────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "kuota":
        uid       = str(q.from_user.id)
        remaining = get_remaining(uid)
        used      = get_user_usage(uid)
        bar       = "🟩" * remaining + "⬜" * (LIMIT_PER_USER - remaining)
        _, days_left = get_week_reset_info()
        await q.message.reply_text(
            f"📊 *Kuota Minggu Ini*\n{bar}\n"
            f"Sudah pakai `{used}` · Sisa `{remaining}/{LIMIT_PER_USER}`\n"
            f"🔄 Reset {days_left} hari lagi",
            parse_mode="Markdown"
        )

    elif q.data == "help":
        await q.message.reply_text(
            "📖 *Cara Pakai:*\n\n"
            "1️⃣ /login → Login ke akun GetContact\n"
            "2️⃣ Kirim nomor: `+628123456789`\n"
            "3️⃣ Bot tampilkan nama & tag\n\n"
            "/start /login /logout /status /cek",
            parse_mode="Markdown"
        )

    elif q.data == "do_login":
        await q.message.reply_text("👆 Ketik /login untuk memulai login GetContact.")

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    print("🤖 Bot GetContact starting (Railway mode)...")
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={WAIT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_otp)]},
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )

    app.add_handler(login_conv)
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cek",    cek_kuota))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Polling dimulai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
