import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
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


def is_admin(user_id):
    return int(user_id) in ADMIN_IDS


async def require_admin(update: Update):
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
        print("⚠️ No GetContact session. Admin must use /setsession.")


def audience_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔎 Cara Cek", callback_data="help"),
            InlineKeyboardButton("📊 Kuota Saya", callback_data="quota"),
        ]
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Dashboard", callback_data="admin_dash"),
            InlineKeyboardButton("🔐 Session", callback_data="admin_session"),
        ],
        [
            InlineKeyboardButton("🧾 Aktivitas", callback_data="admin_recent"),
            InlineKeyboardButton("🏆 Top User", callback_data="admin_top"),
        ],
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

    tag_texts = [
        t.get("tag", "")
        for t in tags
        if isinstance(t, dict) and t.get("tag")
    ]
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
            "User tidak melihat menu login/session.\n\n"
            "Gunakan /admin untuk dashboard.\n"
            "Gunakan /setsession TOKEN untuk menyimpan session resmi.",
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
        "🔐 Kamu tidak perlu login GetContact.",
        parse_mode="Markdown",
        reply_markup=audience_keyboard(),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    await show_dashboard(update, context)


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = dashboard_stats()
    session = "🟢 Aktif" if gtc.token else "🔴 Belum di-set"

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
        "`/setsession TOKEN`\n"
        "`/sessioninfo`\n"
        "`/logout`\n"
        "`/block ID`\n"
        "`/unblock ID`\n"
        "`/resetquota ID`"
    )

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=admin_keyboard(),
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=admin_keyboard(),
            )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=admin_keyboard(),
        )


async def setsession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "⛔ Jalankan `/setsession` hanya di private chat dengan bot.",
            parse_mode="Markdown",
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Format:\n`/setsession TOKEN`\n\n"
            "Masukkan token/session valid hasil login resmi.",
            parse_mode="Markdown",
        )
        return

    token = " ".join(context.args).strip()

    try:
        gtc.set_session(token, GTC_PHONE)
        log_admin(update.effective_user.id, "set_session")

        # Best effort: delete message containing token from private chat.
        try:
            await update.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "✅ *Session tersimpan.*\n\n"
                "Audience sekarang akan memakai session admin ini."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Gagal menyimpan session: `{str(e)[:500]}`",
            parse_mode="Markdown",
        )


async def sessioninfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    d = gtc.ensure_device()

    if gtc.token:
        masked = (
            gtc.token[:6] + "..." + gtc.token[-4:]
            if len(gtc.token) > 12
            else "***"
        )
        await update.message.reply_text(
            "🟢 *Session aktif*\n\n"
            f"Token: `{masked}`\n"
            f"Device lokal: `{d.get('brand')} {d.get('model')}`\n"
            f"Android: `{d.get('android_version')}`\n"
            f"Device ID: `{d.get('device_id')[:8]}...`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🔴 Belum ada session.\nGunakan `/setsession TOKEN`.",
            parse_mode="Markdown",
        )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    clear_session()
    log_admin(update.effective_user.id, "logout")
    await update.message.reply_text("🔓 Session admin dihapus.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if gtc.token:
        await update.message.reply_text("🟢 Shared session aktif.")
    else:
        await update.message.reply_text(
            "🔴 Shared session belum aktif. Gunakan /setsession."
        )


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Format: `/block TELEGRAM_ID`",
            parse_mode="Markdown",
        )
        return

    set_blocked(context.args[0], True)
    log_admin(update.effective_user.id, f"block:{context.args[0]}")
    await update.message.reply_text("✅ User diblokir.")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Format: `/unblock TELEGRAM_ID`",
            parse_mode="Markdown",
        )
        return

    set_blocked(context.args[0], False)
    log_admin(update.effective_user.id, f"unblock:{context.args[0]}")
    await update.message.reply_text("✅ User dibuka kembali.")


async def reset_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Format: `/resetquota TELEGRAM_ID`",
            parse_mode="Markdown",
        )
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
            f"📦 Kuota minggu ini sudah habis.\n"
            f"Reset sekitar {days_left} hari lagi."
        )
        return

    msg = await update.message.reply_text("🔎 Sedang mencari...")

    try:
        data = await gtc.search(phone)
        ok = not data.get("error")

        if not is_admin(user.id):
            increment_usage(uid)

        log_search(uid, phone, "success" if ok else "failed")

        result = format_result(data, phone)

        if not is_admin(user.id):
            remaining = get_remaining(uid)
            result += f"\n\n📦 Sisa kuota: `{remaining}/{LIMIT_PER_USER}`"

        await msg.edit_text(result, parse_mode="Markdown")

    except asyncio.TimeoutError:
        log_search(uid, phone, "timeout")
        await msg.edit_text("⏱ Server timeout. Coba beberapa saat lagi.")

    except Exception as e:
        log_search(uid, phone, "error")
        await msg.edit_text(
            f"❌ Sistem error: `{str(e)[:500]}`",
            parse_mode="Markdown",
        )


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
            f"📊 *Kuota Kamu*\n\n"
            f"Terpakai: `{used}`\n"
            f"Sisa: `{remaining}/{LIMIT_PER_USER}`\n"
            f"Reset sekitar `{days_left}` hari lagi.",
            parse_mode="Markdown",
        )
        return

    if q.data == "help":
        await q.message.reply_text(
            "📖 *Cara pakai*\n\n"
            "Kirim nomor dalam format `628xxxxxxxxxx`.\n"
            "Kamu tidak perlu login GetContact.",
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
            if gtc.token:
                d = gtc.ensure_device()
                await q.message.reply_text(
                    "🟢 *Session aktif*\n\n"
                    f"Device lokal: `{d.get('brand')} {d.get('model')}`",
                    parse_mode="Markdown",
                )
            else:
                await q.message.reply_text(
                    "🔴 Belum ada session.\nGunakan `/setsession TOKEN`.",
                    parse_mode="Markdown",
                )

        elif q.data == "admin_recent":
            rows = recent_searches()

            if not rows:
                text = "🧾 Belum ada aktivitas."
            else:
                lines = ["🧾 *Aktivitas terbaru*"]
                for r in rows:
                    who = (
                        r.get("username")
                        or r.get("first_name")
                        or r["telegram_id"]
                    )
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
                    who = (
                        r.get("username")
                        or r.get("first_name")
                        or r["telegram_id"]
                    )
                    lines.append(f"{i}. {who} — `{r['used']}` cek")
                text = "\n".join(lines)

            await q.message.reply_text(text, parse_mode="Markdown")


def main():
    print("🤖 Community lookup bot starting...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("setsession", setsession))
    app.add_handler(CommandHandler("sessioninfo", sessioninfo))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("block", block_user))
    app.add_handler(CommandHandler("unblock", unblock_user))
    app.add_handler(CommandHandler("resetquota", reset_quota))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("✅ Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
