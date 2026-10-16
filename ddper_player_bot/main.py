import os
import re
import json
import logging
import asyncio
import time
import threading
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("ddper-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DDPER_URL = "https://ddper.ir"
DDNET_API_URL = "https://ddnet.org/players/?json2={player}"
DEFAULT_PLAYER = os.getenv("DDPER_DEFAULT_PLAYER", "FXI").strip() or "FXI"
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Add it in Railway Variables.")

MENU = ReplyKeyboardMarkup(
    [
        ["📊 آمار بازیکن", "🔎 جستجوی بازیکن"],
        ["🏆 رتبه‌بندی", "🗺 مپ‌ها"],
        ["👥 کلن‌ها", "🖥 وضعیت سرورها"],
        ["🎨 اسکین‌ها", "🛒 فروشگاه"],
        ["⬇️ دانلود بازی", "ℹ️ راهنما"],
    ],
    resize_keyboard=True,
)
CACHE_TTL = 120
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def cached(key, ttl, loader):
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    value = loader()
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), value)
    return value

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DDPERTelegramBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
}

SECTIONS = {
    "🏠 خانه": ("/", "خانهٔ DDPER"),
    "🏆 رتبه‌بندی": ("/ranks", "رتبه‌بندی بازیکنان"),
    "🗺 مپ‌ها": ("/maps", "آرشیو نقشه‌ها"),
    "👥 کلن‌ها": ("/clans", "کلن‌ها و اعضا"),
    "🖥 وضعیت سرورها": ("/status", "وضعیت سرورها"),
    "🎨 اسکین‌ها": ("/skins", "گالری اسکین‌ها"),
    "🛒 فروشگاه": ("/shop", "فروشگاه اشتراک‌ها"),
    "⬇️ دانلود بازی": ("/download", "دانلود کلاینت بازی"),
    "📘 آموزش": ("/wiki", "آموزش‌ها"),
    "📜 قوانین": ("/rules", "قوانین"),
}
LINKS = {
    "Discord": "https://ddper.ir/discord",
    "Telegram": "https://t.me/TeeWorlds",
    "Website": DDPER_URL,
}

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def _fetch_json_player(name):
    response = requests.get(
        DDNET_API_URL.format(player=quote(name, safe="")),
        headers=HEADERS,
        timeout=(3, 7),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("player"):
        return None
    return data


def fetch_json_player(name):
    return cached("player:" + name.casefold(), 45, lambda: _fetch_json_player(name))

def _fetch_site_section(path):
    url = urljoin(DDPER_URL, path)
    response = requests.get(url, headers=HEADERS, timeout=(3, 7))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    lines = []
    for node in main.find_all(["h1", "h2", "h3", "p", "li", "tr"], limit=90):
        text = clean(node.get_text(" ", strip=True))
        if text and text not in lines and len(text) > 1:
            lines.append(text)
    # Extract useful structured text when the page is rendered server-side.
    content = "\n".join(lines[:32])
    return {"url": url, "title": title, "content": content}


def fetch_site_section(path):
    return cached("section:" + path, 300, lambda: _fetch_site_section(path))

def rank_text(value):
    if not isinstance(value, dict):
        return "ثبت نشده"
    rank = value.get("rank")
    points = value.get("points")
    if rank is None:
        return "ثبت نشده"
    try:
        rank = f"{int(rank):,}"
    except (TypeError, ValueError):
        rank = str(rank)
    if points is not None:
        try:
            points = f"{int(points):,}"
        except (TypeError, ValueError):
            points = str(points)
        return f"رتبهٔ {rank} · {points} امتیاز"
    return f"رتبهٔ {rank}"

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

def make_player_report(player_name, data):
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
        f"🎮 <b>آمار بازیکن {player}</b>", "",
        "🌍 <b>آمار کلی</b>",
        f"🏆 رتبهٔ جهانی: <b>{rank_text(rank)}</b>",
        f"🤝 رتبهٔ تیمی: <b>{rank_text(team_rank)}</b>",
        f"⭐ امتیاز کل سیستم: <b>{total_points:,}</b>" if isinstance(total_points, int) else f"⭐ امتیاز کل سیستم: <b>{clean(total_points)}</b>",
        f"💠 امتیاز بازیکن: <b>{earned_points:,}</b>" if isinstance(earned_points, int) else f"💠 امتیاز بازیکن: <b>{clean(earned_points)}</b>",
        f"📅 امتیاز ۷ روز اخیر: <b>{rank_text(week)}</b>",
        f"🗓️ امتیاز ۳۰ روز اخیر: <b>{rank_text(month)}</b>",
        f"📆 امتیاز ۳۶۵ روز اخیر: <b>{rank_text(year)}</b>",
        f"🖥️ سرور محبوب: <b>{clean(favorite.get('server', '—'))}</b>",
    ]
    if first:
        lines += ["", "🥇 <b>اولین رکورد</b>",
                  f"🗺️ نقشه: <b>{clean(first.get('map', '—'))}</b>",
                  f"⏱️ زمان: <b>{seconds_text(first.get('time', '—'))}</b>",
                  f"🕒 تاریخ: <b>{timestamp_text(first.get('timestamp'))}</b>"]
    lines += ["", "🔥 <b>۱۰ رکورد اخیر</b>"]
    if recent:
        for i, item in enumerate(recent[:10], 1):
            map_name = clean(item.get("map", "نقشه نامشخص"))
            lines.append(f"{i}. <b>{map_name}</b> — {seconds_text(item.get('time', '—'))}")
            suffix = " · ".join(x for x in (clean(item.get("type", "")), clean(item.get("country", ""))) if x)
            if suffix:
                lines.append(f"   <i>{suffix}</i>")
            lines.append(f"   <i>{timestamp_text(item.get('timestamp'))}</i>")
    else:
        lines.append("رکورد اخیر در خروجی عمومی ثبت نشده است.")
    hours = data.get("hours_played_past_365_days")
    if hours is not None:
        lines += ["", f"⏳ ساعت بازی در ۳۶۵ روز اخیر: <b>{clean(hours)}</b>"]
    lines += ["", f'🌐 <a href="{DDPER_URL}/players/{quote(player, safe="")}">پروفایل در سایت DDPER</a>']
    return "\n".join(lines)

async def send_player(update, player_name):
    msg = await update.effective_message.reply_text("⏳ در حال دریافت آمار بازیکن…", reply_markup=MENU)
    try:
        data = await asyncio.to_thread(fetch_json_player, player_name)
        if not data:
            await msg.edit_text(
                f"❌ بازیکن «{player_name}» در دیتابیس عمومی پیدا نشد. نام داخل بازی را دقیق بفرست."
            )
            return
        report = make_player_report(player_name, data)
        if len(report) > 3900:
            report = report[:3650] + f'\n…\n<a href="{DDPER_URL}/players/{quote(player_name, safe="")}">مشاهده پروفایل کامل</a>'
        await msg.edit_text(report, parse_mode="HTML", disable_web_page_preview=True)
    except requests.RequestException as exc:
        log.warning("Player API failed: %s", type(exc).__name__)
        await msg.edit_text("⚠️ سرویس آمار بازیکن فعلاً پاسخ نمی‌دهد؛ کمی بعد دوباره امتحان کن.")
    except Exception:
        log.exception("Player report failed")
        await msg.edit_text("⚠️ خطا هنگام آماده‌سازی آمار. لاگ سرویس برای بررسی ثبت شد.")

async def send_section(update, section_name):
    path, label = SECTIONS[section_name]
    url = urljoin(DDPER_URL, path)
    msg = await update.effective_message.reply_text(f"⏳ در حال دریافت اطلاعات «{label}» از DDPER…", reply_markup=MENU)
    try:
        page = await asyncio.to_thread(fetch_site_section, path)
        text = [f"🌐 <b>{label}</b>"]
        if page["content"]:
            text += ["", page["content"][:2700]]
        else:
            text += [
                "",
                "این بخش در سایت با داده‌های پویا بارگذاری می‌شود و متن کامل آن از HTML اولیه قابل دریافت نیست. برای دیدن داده‌های زنده، منبع سایت را باز کن؛ اتصال مستقیم به API این بخش هنوز نیاز به شناسایی مسیر دادهٔ آن دارد."
            ]
        text += ["", f'🔗 <a href="{url}">باز کردن بخش {label} در DDPER</a>']
        await msg.edit_text("\n".join(text), parse_mode="HTML", disable_web_page_preview=True, reply_markup=MENU)
    except requests.RequestException as exc:
        log.warning("DDPER section fetch failed for %s: %s", path, type(exc).__name__)
        await msg.edit_text(f"⚠️ فعلاً نتوانستم اطلاعات این بخش را از سایت دریافت کنم.\n<a href=\"{url}\">باز کردن {label}</a>", parse_mode="HTML", disable_web_page_preview=True, reply_markup=MENU)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "سلام! 👋 به ربات DDPER خوش آمدی.\n\n"
        "از منو می‌توانی آمار بازیکنان را داخل تلگرام ببینی و بخش‌های اصلی سایت را باز کنی: رتبه‌بندی، مپ‌ها، کلن‌ها، وضعیت سرورها، اسکین‌ها، فروشگاه و دانلود.\n"
        "برای جستجوی آمار بازیکن از /player نام استفاده کن.",
        reply_markup=MENU,
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_player(update, DEFAULT_PLAYER)

async def search_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("نام بازیکن را بفرست: /player FXI", reply_markup=MENU)
        return
    player = " ".join(context.args).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]{1,40}", player):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست؛ دوباره بررسی کن.", reply_markup=MENU)
        return
    await send_player(update, player)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    if text == "📊 آمار بازیکن":
        await send_player(update, DEFAULT_PLAYER)
    elif text == "🔎 جستجوی بازیکن":
        await update.effective_message.reply_text("نام بازیکن را بفرست یا دستور /player NAME را استفاده کن؛ نمونه: /player FXI", reply_markup=MENU)
    elif text in SECTIONS:
        await send_section(update, text)
    elif text == "ℹ️ راهنما":
        await update.effective_message.reply_text(
            "📚 راهنمای ربات DDPER\n"
            "/start — منوی اصلی\n"
            "/profile — آمار بازیکن پیش‌فرض\n"
            "/player NAME — جستجوی بازیکن\n\n"
            "بخش‌های سایت: رتبه‌بندی، مپ‌ها، کلن‌ها، وضعیت سرورها، اسکین‌ها، فروشگاه و دانلود.\n"
            "آمار بازیکن از API عمومی DDNet دریافت می‌شود؛ صفحات دیگر از سایت DDPER خوانده می‌شوند. بخش‌هایی که با JavaScript بارگذاری می‌شوند ممکن است برای نمایش دادهٔ زنده به API اختصاصی سایت نیاز داشته باشند.",
            reply_markup=MENU,
        )
    else:
        await update.effective_message.reply_text("از دکمه‌های منو استفاده کن یا /player NAME را بفرست.", reply_markup=MENU)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("player", search_player))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    log.info("DDPER Telegram bot starting; site sections enabled")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
