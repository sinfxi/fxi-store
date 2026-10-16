import os
import re
import json
import logging
import asyncio
import time
import threading
import sqlite3
import random
from html import escape
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
        ["⚖️ مقایسه بازیکن‌ها", "⭐ بازیکن‌های محبوب"],
        ["🕘 جستجوهای اخیر", "🎲 بازیکن تصادفی"],
        ["🏆 رتبه‌بندی", "🗺 مپ‌ها"],
        ["👥 کلن‌ها", "🖥 وضعیت سرورها"],
        ["🎨 اسکین‌ها", "🛒 فروشگاه"],
        ["⬇️ دانلود بازی", "ℹ️ راهنما"],
    ],
    resize_keyboard=True,
)
DB_PATH = os.getenv("DDPER_DB_PATH", "/tmp/ddper_bot.sqlite3")


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER NOT NULL, player TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, player))")
    conn.execute("CREATE TABLE IF NOT EXISTS recent (user_id INTEGER NOT NULL, player TEXT NOT NULL, searched_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    return conn


def save_search(user_id, player):
    try:
        with db_connect() as conn:
            conn.execute("INSERT INTO recent(user_id, player) VALUES (?, ?)", (user_id, player))
            conn.execute("DELETE FROM recent WHERE user_id=? AND rowid NOT IN (SELECT rowid FROM recent WHERE user_id=? ORDER BY searched_at DESC, rowid DESC LIMIT 10)", (user_id, user_id))
    except sqlite3.Error:
        log.exception("Could not save player search")


def toggle_favorite(user_id, player):
    with db_connect() as conn:
        exists = conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND player=? COLLATE NOCASE", (user_id, player)).fetchone() is not None
        if exists:
            conn.execute("DELETE FROM favorites WHERE user_id=? AND player=? COLLATE NOCASE", (user_id, player))
            return False
        conn.execute("INSERT OR IGNORE INTO favorites(user_id, player) VALUES (?, ?)", (user_id, player))
        return True


def get_user_players(table, user_id, limit=10):
    if table not in ("favorites", "recent"):
        return []
    order = "created_at DESC" if table == "favorites" else "searched_at DESC, rowid DESC"
    with db_connect() as conn:
        rows = conn.execute(f"SELECT player FROM {table} WHERE user_id=? ORDER BY {order} LIMIT ?", (user_id, limit)).fetchall()
        return [row[0] for row in rows]


CACHE_TTL = 180
_CACHE = {}
_CACHE_LOCK = threading.Lock()
_KEY_LOCKS = {}


def cached(key, ttl, loader):
    # Cache hits return immediately; only one request per key runs on a cold cache.
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
        key_lock = _KEY_LOCKS.setdefault(key, threading.Lock())
    with key_lock:
        now = time.monotonic()
        with _CACHE_LOCK:
            entry = _CACHE.get(key)
            if entry and now - entry[0] < ttl:
                return entry[1]
            stale_value = entry[1] if entry else None
        try:
            value = loader()
        except Exception:
            # If the upstream API has a brief outage, serve the last known result.
            if stale_value is not None:
                log.warning("Upstream fetch failed for %s; serving stale cached data", key)
                return stale_value
            raise
        with _CACHE_LOCK:
            _CACHE[key] = (time.monotonic(), value)
            if len(_CACHE) > 1000:
                cutoff = time.monotonic() - 900
                for cache_key, (stamp, _) in list(_CACHE.items()):
                    if stamp < cutoff:
                        _CACHE.pop(cache_key, None)
                        _KEY_LOCKS.pop(cache_key, None)
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
        timeout=(2, 4),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("player"):
        return None
    return data


def fetch_json_player(name):
    return cached("player:" + name.casefold(), 180, lambda: _fetch_json_player(name))

def _fetch_site_section(path):
    url = urljoin(DDPER_URL, path)
    response = requests.get(url, headers=HEADERS, timeout=(2, 4))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    lines = []
    for node in main.find_all(["h1", "h2", "h3", "p", "li", "tr"], limit=60):
        value = clean(node.get_text(" ", strip=True))
        if value and value not in lines and len(value) > 1:
            lines.append(value)
    # Extract useful structured text when the page is rendered server-side.
    content = "\n".join(lines[:24])
    return {"url": url, "title": title, "content": content}


def fetch_site_section(path):
    return cached("section:" + path, 600, lambda: _fetch_site_section(path))

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
    save_search(update.effective_user.id if update.effective_user else 0, player_name)
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
    msg = await update.effective_message.reply_text(
        f"⏳ در حال دریافت اطلاعات «{label}» از DDPER…", reply_markup=MENU
    )
    try:
        page = await asyncio.to_thread(fetch_site_section, path)
        parts = [f"🌐 <b>{escape(label)}</b>"]
        if page["content"]:
            # Escape untrusted site text so Telegram's HTML parser cannot reject it.
            parts += ["", escape(page["content"][:2400])]
        else:
            parts += [
                "",
                "این بخش با داده‌های پویا بارگذاری می‌شود و متن کامل آن از HTML اولیه قابل دریافت نیست. برای دیدن اطلاعات زنده، صفحهٔ سایت را باز کن."
            ]
        parts += ["", f'🔗 <a href="{url}">باز کردن بخش {escape(label)} در DDPER</a>']
        response_text = "\n".join(parts)
        try:
            await msg.edit_text(response_text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            # Never leave the user with only a spinner if Telegram rejects editing.
            log.exception("Could not edit section response for %s; sending a new message", path)
            await update.effective_message.reply_text(
                response_text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=MENU
            )
    except requests.RequestException as exc:
        log.warning("DDPER section fetch failed for %s: %s", path, type(exc).__name__)
        fallback = f'⚠️ دریافت اطلاعات «{escape(label)}» از سایت ناموفق بود.\n<a href="{url}">باز کردن صفحه</a>'
        try:
            await msg.edit_text(fallback, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            await update.effective_message.reply_text(
                f"⚠️ دریافت اطلاعات «{label}» ناموفق بود.\n{url}", reply_markup=MENU
            )
    except Exception:
        log.exception("Unexpected error while loading DDPER section %s", path)
        try:
            await msg.edit_text("⚠️ هنگام آماده‌سازی پاسخ خطایی رخ داد؛ دوباره امتحان کن.")
        except Exception:
            await update.effective_message.reply_text(
                "⚠️ هنگام آماده‌سازی پاسخ خطایی رخ داد؛ دوباره امتحان کن.", reply_markup=MENU
            )


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
    elif text == "⚖️ مقایسه بازیکن‌ها":
        await update.effective_message.reply_text("برای مقایسه دو بازیکن از این دستور استفاده کن:\n/compare FXI PlayerName", reply_markup=MENU)
    elif text == "⭐ بازیکن‌های محبوب":
        await list_favorites(update, context)
    elif text == "🕘 جستجوهای اخیر":
        await recent_searches(update, context)
    elif text == "🎲 بازیکن تصادفی":
        await random_player(update, context)
    elif text == "🔎 جستجوی بازیکن":
        await update.effective_message.reply_text("نام بازیکن را بفرست یا دستور /player NAME را استفاده کن؛ نمونه: /player FXI", reply_markup=MENU)
    elif text in SECTIONS:
        await send_section(update, text)
    elif text == "ℹ️ راهنما":
        await update.effective_message.reply_text(
            "📚 راهنمای ربات DDPER\n"
            "/start — منوی اصلی\n"
            "/profile — آمار بازیکن پیش‌فرض\n"
            "/player NAME — جستجوی بازیکن\n"
            "/compare NAME1 NAME2 — مقایسه دو بازیکن\n"
            "/favorite NAME — افزودن/حذف بازیکن محبوب\n"
            "/favorites — فهرست محبوب‌ها\n"
            "/recent — آخرین جستجوها\n\n"
            "بخش‌های سایت: رتبه‌بندی، مپ‌ها، کلن‌ها، وضعیت سرورها، اسکین‌ها، فروشگاه و دانلود.\n"
            "آمار بازیکن از API عمومی DDNet دریافت می‌شود؛ صفحات دیگر از سایت DDPER خوانده می‌شوند. بخش‌هایی که با JavaScript بارگذاری می‌شوند ممکن است برای نمایش دادهٔ زنده به API اختصاصی سایت نیاز داشته باشند.",
            reply_markup=MENU,
        )
    else:
        await update.effective_message.reply_text("از دکمه‌های منو استفاده کن یا /player NAME را بفرست.", reply_markup=MENU)

async def compare_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.effective_message.reply_text("دو نام بازیکن بده؛ مثال: /compare FXI PlayerName", reply_markup=MENU)
        return
    names = context.args
    if any(not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]{1,40}", name) for name in names):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست.", reply_markup=MENU)
        return
    status = await update.effective_message.reply_text("⚖️ دارم آمار دو بازیکن را مقایسه می‌کنم…", reply_markup=MENU)
    try:
        a, b = await asyncio.gather(asyncio.to_thread(fetch_json_player, names[0]), asyncio.to_thread(fetch_json_player, names[1]))
        if not a or not b:
            await status.edit_text("یکی از بازیکن‌ها پیدا نشد؛ نام‌ها را بررسی کن.")
            return
        def points(data):
            value = (data.get("points") or {}).get("points", 0)
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0
        p1, p2 = points(a), points(b)
        winner = names[0] if p1 > p2 else names[1] if p2 > p1 else "مساوی"
        report = (
            f"⚖️ <b>مقایسه بازیکنان</b>\n\n"
            f"🎮 <b>{escape(names[0])}</b>\n⭐ امتیاز: <b>{p1:,.0f}</b>\n🏆 رتبه: <b>{escape(rank_text(a.get('rank') or {}))}</b>\n\n"
            f"🎮 <b>{escape(names[1])}</b>\n⭐ امتیاز: <b>{p2:,.0f}</b>\n🏆 رتبه: <b>{escape(rank_text(b.get('rank') or {}))}</b>\n\n"
            f"🥇 برتری امتیاز: <b>{escape(winner)}</b>"
        )
        await status.edit_text(report, parse_mode="HTML")
    except Exception:
        log.exception("Compare failed")
        await status.edit_text("⚠️ مقایسه فعلاً انجام نشد؛ کمی بعد دوباره امتحان کن.")


async def favorite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("برای افزودن یا حذف بازیکن محبوب: /favorite FXI", reply_markup=MENU)
        return
    player = " ".join(context.args).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-\[\] ]{1,40}", player):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست.", reply_markup=MENU)
        return
    added = toggle_favorite(update.effective_user.id, player)
    label = "⭐ به فهرست محبوب‌ها اضافه شد: " if added else "🗑 از فهرست محبوب‌ها حذف شد: "
    await update.effective_message.reply_text(label + player, reply_markup=MENU)


async def list_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = get_user_players("favorites", update.effective_user.id)
    if not players:
        await update.effective_message.reply_text("هنوز بازیکن محبوبی نداری. برای افزودن: /favorite FXI", reply_markup=MENU)
        return
    body = "\n".join("• " + escape(p) + " — /player " + escape(p) for p in players)
    await update.effective_message.reply_text("⭐ <b>بازیکن‌های محبوب تو</b>\n" + body, parse_mode="HTML", reply_markup=MENU)


async def recent_searches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = get_user_players("recent", update.effective_user.id)
    if not players:
        await update.effective_message.reply_text("هنوز جستجویی ثبت نشده؛ با /player NAME شروع کن.", reply_markup=MENU)
        return
    body = "\n".join("• " + escape(p) + " — /player " + escape(p) for p in players)
    await update.effective_message.reply_text("🕘 <b>آخرین جستجوها</b>\n" + body, parse_mode="HTML", reply_markup=MENU)


async def random_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = get_user_players("favorites", update.effective_user.id)
    if not players:
        await update.effective_message.reply_text("برای انتخاب تصادفی، اول چند بازیکن با /favorite NAME ذخیره کن.", reply_markup=MENU)
        return
    await send_player(update, random.choice(players))


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("player", search_player))
    app.add_handler(CommandHandler("compare", compare_players))
    app.add_handler(CommandHandler("favorite", favorite_command))
    app.add_handler(CommandHandler("favorites", list_favorites))
    app.add_handler(CommandHandler("recent", recent_searches))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    log.info("DDPER Telegram bot starting; site sections enabled")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
