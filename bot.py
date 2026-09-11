import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)

from config import BOT_TOKEN, GTC_PHONE, LIMIT_PER_USER, ADMIN_IDS
from db import (
    init_db,
    touch_user,
    is_blocked,
    set_blocked,
    get_user_usage,
    increment_usage,
    get_remaining,
    get_week_reset_info,
    reset_user_usage,
    log_search,
    log_admin,
    dashboard_stats,
    top_users,
    recent_searches,
)
from gtc_auth import gtc, clear_session

WAIT_OTP = 1


def is_admin(user_id):
    return int(user_id) in ADMIN_IDS


async def require_admin(update):
    if not is_admin(update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("Admin only.", show_alert=True)
        elif update.message:
            await update.message.reply_text("⛔ Fitur ini khusus admin.")
        return False
    return True


async def post_init(application):
    init_db()
    if gtc.restore_session():
        print("✅ Shared GetContact session restored.")
    else:
        print("⚠️ No GetContact session. Admin must /login once.")


def audience_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Cara Cek", callback_data="help"),
         InlineKeyboardButton("📊 Kuota Saya", callback_data="quota")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="admin_dash"),
         InlineKeyboardButton("🔐 Session", callback_data="admin_session")],
        [InlineKeyboardButton("🧾 Aktivitas", callback_data="admin_recent"),
         InlineKeyboardButton("🏆 Top User", callback_data="admin_top")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_dash")],
    ])


def format_result(data, phone):
    if data.get("error"):
        msg = data.get("message") or data.get("raw") or "Upstream error"
        return f"❌ *Pencarian gagal*\n`{str(msg)[:600]}`"

    result = data.get("result") or {}
    profiles = result.get("profiles") or []
    tags = result.get("tags") or []
    spam = result.get("spamInfo") or {}

    lines = [f"🔎 *Hasil Pencarian*\n📱 `{phone}`\n"]
    if profiles:
        lines.append(f"👤 *Nama ditemukan ({len(profiles)}):*")
        for i, p in enumerate(profiles[:15], 1):
            lines.append(f"`{i}.` {p.get('name', '—')}")
        if len(profiles) > 15:
            lines.append(f"_+{len(profiles)-15} nama lainnya_")
    else:
        lines.append("👤 Tidak ada nama yang ditampilkan.")

    tag_texts = [t.get("tag", "") for t in tags if isinstance(t, dict) and t.get("tag")]
    if tag_texts:
        lines.append("\n🏷 *Tag:* " + ", ".join(tag_texts[:20]))

    if spam:
        lines.append(
            f"\n⚠️ *Spam:* `{spam.get('count', 0)}` laporan"
            + (f" · {spam.get('type')}" if spam.get("type") else "")
        )
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_user(user)

    if is_admin(user.id):
        await update.message.reply_text(
            "🛡 *ADMIN — GetContact Community Bot*\n\n"
            "Audience memakai session akun GetContact milik admin.\n"
            "User tidak melihat menu login/OTP.\n\n"
            "Gunakan /admin untuk dashboard.",
            parse_mode="Markdown",
            reply_markup=admin_keyboard(),
        )
        return

    remaining = get_remaining(str(user.id))
    await update.message.reply_text(
        f"👋 Halo *{user.first_name or 'kawan'}*!\n\n"
        "🔎 Kirim nomor HP yang ingin dicek.\n"
        "Contoh: `628123456789`\n\n"
        f"📦 Kuota minggu ini: `{remaining}/{LIMIT_PER_USER}`\n"
        "🔐 Sistem menggunakan akun internal — kamu tidak perlu login.",
        parse_mode="Markdown",
        reply_markup=audience_keyboard(),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    await show_dashboard(update, context)


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = dashboard_stats()
    session = "🟢 Aktif" if gtc.token else "🔴 Belum login"
    text = (
        "🛡 *ADMIN DASHBOARD*\n\n"
        f"🔐 Session: {session}\n"
        f"👥 Total user: `{s['total_users']}`\n"
        f"🟢 Aktif hari ini: `{s['active_today']}`\n"
        f"🔎 Cek hari ini: `{s['searches_today']}`\n"
        f"✅ Berhasil hari ini: `{s['success_today']}`\n"
        f"📈 Cek 7 hari: `{s['searches_7d']}`\n"
        f"🚫 Diblokir: `{s['blocked']}`\n\n"
        "Admin commands:\n"
        "`/login` `/status` `/logout`\n"
        "`/block ID` `/unblock ID` `/resetquota ID`"
    )
    if update.callback_query:
        await update.callback_query.message.edit_text(
            text, parse_mode="Markdown", reply_markup=admin_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=admin_keyboard()
        )


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return ConversationHandler.END

    msg = await update.message.reply_text(
        "🔐 *Admin login GetContact*\n\nMembuat device session...",
        parse_mode="Markdown",
    )
    try:
        reg = await gtc.register_device()
        if reg.get("error"):
            await msg.edit_text(f"❌ Register device gagal:\n`{str(reg)[:800]}`", parse_mode="Markdown")
            return ConversationHandler.END

        await msg.edit_text(
            f"📲 Meminta OTP untuk `+{GTC_PHONE}`...\n"
            "Preferensi: *WhatsApp* (jika didukung server GetContact).",
            parse_mode="Markdown",
        )
        resp = await gtc.send_otp(GTC_PHONE, prefer_whatsapp=True)
        if resp.get("error"):
            await msg.edit_text(
                f"❌ OTP request ditolak.\n`{str(resp)[:900]}`",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        await msg.edit_text(
            "✅ Request OTP diterima.\n\n"
            "Masukkan kode OTP yang diterima admin.\n"
            "_Delivery bisa tetap SMS bila server GetContact tidak mendukung pemilihan WhatsApp._",
            parse_mode="Markdown",
        )
        log_admin(update.effective_user.id, "request_otp")
        return WAIT_OTP
    except Exception as e:
        await msg.edit_text(f"❌ Login error: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END


async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return ConversationHandler.END

    otp = update.message.text.strip()
    if not otp.isdigit() or not (4 <= len(otp) <= 8):
        await update.message.reply_text("⚠️ Format OTP tidak valid.")
        return WAIT_OTP

    msg = await update.message.reply_text("🔄 Memverifikasi...")
    result = await gtc.verify_otp(otp)
    if gtc.token:
        log_admin(update.effective_user.id, "login_success")
        await msg.edit_text(
            "✅ *Login GetContact berhasil.*\n\n"
            "Session ini sekarang dipakai bersama oleh audience.",
            parse_mode="Markdown",
        )
    else:
        await msg.edit_text(
            f"❌ Verifikasi gagal.\n`{str(result)[:900]}`",
            parse_mode="Markdown",
        )
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if gtc.token:
        d = gtc.device or {}
        await update.message.reply_text(
            "🟢 *Shared session aktif*\n\n"
            f"📱 `{d.get('brand','-')} {d.get('model','-')}`\n"
            f"📞 `+{gtc.phone or '-'}`\n"
            "🔑 Token tersimpan di SQLite.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("🔴 Belum ada session. Gunakan /login.")


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    clear_session()
    log_admin(update.effective_user.id, "logout")
    await update.message.reply_text("🔓 Shared session dihapus.")


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/block TELEGRAM_ID`", parse_mode="Markdown")
        return
    set_blocked(context.args[0], True)
    log_admin(update.effective_user.id, f"block:{context.args[0]}")
    await update.message.reply_text("✅ User diblokir.")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/unblock TELEGRAM_ID`", parse_mode="Markdown")
        return
    set_blocked(context.args[0], False)
    log_admin(update.effective_user.id, f"unblock:{context.args[0]}")
    await update.message.reply_text("✅ User dibuka kembali.")


async def reset_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Format: `/resetquota TELEGRAM_ID`", parse_mode="Markdown")
        return
    reset_user_usage(context.args[0])
    log_admin(update.effective_user.id, f"resetquota:{context.args[0]}")
    await update.message.reply_text("✅ Kuota user di-reset untuk minggu ini.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    touch_user(user)

    if is_blocked(user.id) and not is_admin(user.id):
        await update.message.reply_text("⛔ Akses kamu sedang dinonaktifkan.")
        return

    text = update.message.text.strip()
    phone = text if text.startswith("+") else f"+{text}"
    digits = phone[1:]

    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        await update.message.reply_text(
            "⚠️ Kirim nomor HP saja.\nContoh: `628123456789`",
            parse_mode="Markdown",
        )
        return

    if not gtc.token:
        await update.message.reply_text(
            "🛠 Sistem pencarian sedang maintenance. Coba lagi nanti."
        )
        return

    uid = str(user.id)
    if not is_admin(user.id) and get_remaining(uid) <= 0:
        _, days_left = get_week_reset_info()
        await update.message.reply_text(
            f"📦 Kuota minggu ini sudah habis.\nReset sekitar {days_left} hari lagi."
        )
        return

    msg = await update.message.reply_text("🔎 Sedang mencari...")
    try:
        data = await gtc.search(phone)
        ok = not data.get("error")

        # Only charge audience on an actual completed request.
        if not is_admin(user.id):
            increment_usage(uid)

        log_search(uid, phone, "success" if ok else "failed")
        remaining = get_remaining(uid)

        result = format_result(data, phone)
        if not is_admin(user.id):
            result += f"\n\n📦 Sisa kuota: `{remaining}/{LIMIT_PER_USER}`"
        await msg.edit_text(result, parse_mode="Markdown")
    except asyncio.TimeoutError:
        log_search(uid, phone, "timeout")
        await msg.edit_text("⏱ Server timeout. Coba beberapa saat lagi.")
    except Exception as e:
        log_search(uid, phone, "error")
        await msg.edit_text(f"❌ Sistem error: `{str(e)[:500]}`", parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    touch_user(q.from_user)

    if q.data == "quota":
        uid = str(q.from_user.id)
        remaining = get_remaining(uid)
        used = get_user_usage(uid)
        _, days_left = get_week_reset_info()
        await q.message.reply_text(
            f"📊 *Kuota Kamu*\n\nTerpakai: `{used}`\n"
            f"Sisa: `{remaining}/{LIMIT_PER_USER}`\n"
            f"Reset sekitar `{days_left}` hari lagi.",
            parse_mode="Markdown",
        )
        return

    if q.data == "help":
        await q.message.reply_text(
            "📖 *Cara pakai*\n\n"
            "Kirim nomor dalam format `628xxxxxxxxxx`.\n"
            "Tidak perlu login GetContact — session dikelola admin.",
            parse_mode="Markdown",
        )
        return

    if q.data.startswith("admin_"):
        if not is_admin(q.from_user.id):
            await q.answer("Admin only.", show_alert=True)
            return

        if q.data == "admin_dash":
            await show_dashboard(update, context)
        elif q.data == "admin_session":
            await q.message.reply_text(
                "🟢 Session aktif." if gtc.token else "🔴 Belum login. Gunakan /login."
            )
        elif q.data == "admin_recent":
            rows = recent_searches()
            if not rows:
                text = "🧾 Belum ada aktivitas."
            else:
                lines = ["🧾 *Aktivitas terbaru*"]
                for r in rows:
                    who = r.get("username") or r.get("first_name") or r["telegram_id"]
                    lines.append(
                        f"• `{r['phone_masked']}` — {r['status']} — {who}"
                    )
                text = "\n".join(lines)
            await q.message.reply_text(text, parse_mode="Markdown")
        elif q.data == "admin_top":
            rows = top_users()
            if not rows:
                text = "🏆 Belum ada penggunaan minggu ini."
            else:
                lines = ["🏆 *Top user minggu ini*"]
                for i, r in enumerate(rows, 1):
                    who = r.get("username") or r.get("first_name") or r["telegram_id"]
                    lines.append(f"{i}. {who} — `{r['used']}` cek")
                text = "\n".join(lines)
            await q.message.reply_text(text, parse_mode="Markdown")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Dibatalkan.")
    return ConversationHandler.END


def main():
    print("🤖 Community lookup bot starting...")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={WAIT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_otp)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(login_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("block", block_user))
    app.add_handler(CommandHandler("unblock", unblock_user))
    app.add_handler(CommandHandler("resetquota", reset_quota))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
