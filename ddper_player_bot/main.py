import os
import re
import json
import logging
import asyncio
from datetime import datetime, timezone

import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("ddper-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PLAYER_URL = os.getenv("DDPER_PLAYER_URL", "https://ddnet.org/players/FXI/").strip()
API_URL = "https://ddnet.org/players/?json2={player}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Add it in Railway Variables.")

MENU = ReplyKeyboardMarkup(
    [["📊 آمار بازیکن FXI", "🔎 جستجوی بازیکن"], ["🌐 لینک پروفایل", "ℹ️ راهنما"]],
    resize_keyboard=True,
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DDPERStatsBot/1.0)",
    "Accept": "application/json,text/plain,*/*",
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def request_player(name):
    """Use DDNet's public JSON endpoint instead of scraping the JavaScript page."""
    response = requests.get(API_URL.format(player=requests.utils.quote(name, safe="")), headers=HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("player"):
        return None
    return data

def rank_text(value):
    if not isinstance(value, dict):
        return "ثبت نشده"
    rank = value.get("rank")
    points = value.get("points")
    if rank is None:
        return "ثبت نشده"
    if points is not None:
        return f"رتبهٔ {rank:,} · {points:,} امتیاز"
    return f"رتبهٔ {rank:,}"

def seconds_text(value):
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return clean(value) or "—"
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours} ساعت و {minutes} دقیقه"
    if minutes:
        return f"{minutes} دقیقه و {seconds} ثانیه"
    return f"{seconds} ثانیه"

def timestamp_text(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "—"

def make_report(player_name, data):
    points = data.get("points") or {}
    team_rank = data.get("team_rank") or {}
    rank = data.get("rank") or {}
    year = data.get("points_last_year") or {}
    month = data.get("points_last_month") or {}
    week = data.get("points_last_week") or {}
    favorite = data.get("favorite_server") or {}
    first = data.get("first_finish") or {}
    recent = data.get("last_finishes") or []
    total_points = points.get("total", "—")
    earned_points = points.get("points", "—")
    player = clean(data.get("player") or player_name)

    lines = [
        f"🎮 <b>آمار بازیکن: {player}</b>",
        "",
        "🌍 <b>آمار کلی</b>",
        f"🏆 رتبهٔ جهانی: <b>{rank_text(rank)}</b>",
        f"🤝 رتبهٔ تیمی: <b>{rank_text(team_rank)}</b>",
        f"⭐ امتیاز کل بازیکنان: <b>{total_points:,}</b>" if isinstance(total_points, int) else f"⭐ کل امتیاز موجود در سیستم: <b>{total_points}</b>",
        f"💠 امتیاز بازیکن: <b>{earned_points:,}</b>" if isinstance(earned_points, int) else f"💠 امتیاز بازیکن: <b>{earned_points}</b>",
        f"📅 امتیاز ۷ روز اخیر: <b>{rank_text(week)}</b>",
        f"🗓️ امتیاز ۳۰ روز اخیر: <b>{rank_text(month)}</b>",
        f"📆 امتیاز ۳۶۵ روز اخیر: <b>{rank_text(year)}</b>",
        f"🖥️ سرور محبوب: <b>{clean(favorite.get('server', '—'))}</b>",
    ]

    if first:
        lines += [
            "",
            "🥇 <b>اولین رکورد</b>",
            f"🗺️ نقشه: <b>{clean(first.get('map', '—'))}</b>",
            f"⏱️ زمان: <b>{seconds_text(first.get('time', '—'))}</b>",
            f"🕒 تاریخ: <b>{timestamp_text(first.get('timestamp'))}</b>",
        ]

    lines += ["", "🔥 <b>۱۰ رکورد اخیر</b>"]
    if recent:
        for index, item in enumerate(recent[:10], 1):
            server = clean(item.get("type", ""))
            country = clean(item.get("country", ""))
            place = clean(item.get("map", "نقشه نامشخص"))
            time_value = seconds_text(item.get("time", "—"))
            stamp = timestamp_text(item.get("timestamp"))
            suffix = " · ".join(x for x in (server, country) if x)
            lines.append(f"{index}. <b>{place}</b> — {time_value}")
            if suffix:
                lines.append(f"   <i>{suffix}</i>")
            lines.append(f"   <i>{stamp}</i>")
    else:
        lines.append("برای این بازیکن رکورد اخیری در خروجی API ثبت نشده است.")

    hours = data.get("hours_played_past_365_days")
    if hours is not None:
        lines += ["", f"⏳ ساعت بازی در ۳۶۵ روز اخیر: <b>{hours}</b>"]

    lines += ["", f'🔗 <a href="https://ddnet.org/players/{requests.utils.quote(player, safe="")}/">مشاهدهٔ پروفایل</a>']
    return "\n".join(lines)

async def send_profile(update, player_name, context):
    msg = await update.effective_message.reply_text("⏳ دارم آمار واقعی بازیکن را از API دریافت می‌کنم…")
    try:
        data = await asyncio.to_thread(request_player, player_name)
        if not data:
            await msg.edit_text(
                f"❌ بازیکن «{player_name}» در دیتابیس عمومی پیدا نشد یا هنوز آماری برایش ثبت نشده.\n"
                "اسم بازیکن را دقیقاً مثل پروفایل سایت بفرست.",
                reply_markup=MENU,
            )
            return
        report = make_report(player_name, data)
        if len(report) > 3900:
            report = report[:3750] + "\n…\n" + f'🔗 <a href="https://ddnet.org/players/{requests.utils.quote(player_name, safe="")}/">پروفایل و رکوردهای بیشتر</a>'
        await msg.edit_text(report, parse_mode="HTML", disable_web_page_preview=True, reply_markup=MENU)
    except requests.RequestException as exc:
        log.warning("Player API request failed: %s", type(exc).__name__)
        await msg.edit_text("⚠️ سرویس آمار فعلاً پاسخ نمی‌دهد. چند لحظه بعد دوباره «آمار بازیکن FXI» را بزن.", reply_markup=MENU)
    except (ValueError, json.JSONDecodeError):
        log.exception("Invalid JSON from player API")
        await msg.edit_text("⚠️ پاسخ سرویس آمار قابل‌خواندن نبود؛ لطفاً کمی بعد دوباره امتحان کن.", reply_markup=MENU)
    except Exception:
        log.exception("Player report failed")
        await msg.edit_text("⚠️ موقع آماده‌کردن آمار خطایی رخ داد. لطفاً دوباره امتحان کن.", reply_markup=MENU)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "سلام! 👋\nمن آمار بازیکنان DDNet را مستقیماً داخل تلگرام نمایش می‌دهم.\n"
        "از دکمهٔ آمار FXI استفاده کن یا نام بازیکن را جست‌وجو کن.",
        reply_markup=MENU,
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_profile(update, "FXI", context)

async def search_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("نام بازیکن را بفرست: /player FXI")
        return
    player = " ".join(context.args).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]{1,40}", player):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست.")
        return
    await send_profile(update, player, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    if text == "📊 آمار بازیکن FXI":
        await profile(update, context)
    elif text == "🔎 جستجوی بازیکن":
        await update.effective_message.reply_text("نام بازیکن را بفرست؛ نمونه: /player FXI", reply_markup=MENU)
    elif text == "🌐 لینک پروفایل":
        await update.effective_message.reply_text(f'🔗 پروفایل FXI: https://ddnet.org/players/FXI/', reply_markup=MENU)
    elif text == "ℹ️ راهنما":
        await update.effective_message.reply_text(
            "📚 راهنما\n/start — شروع\n/profile — آمار FXI\n/player NAME — آمار بازیکن دلخواه\n\n"
            "آمار از API عمومی دریافت می‌شود و داخل همین پیام تلگرام نمایش داده می‌شود.",
            reply_markup=MENU,
        )
    else:
        await update.effective_message.reply_text("برای دیدن آمار، «📊 آمار بازیکن FXI» یا /profile را بزن.", reply_markup=MENU)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("player", search_player))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    log.info("DDPER player bot starting (public JSON API mode)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
