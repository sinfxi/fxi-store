import os
import re
import json
import logging
import asyncio
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("ddper-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PLAYER_URL = os.getenv("DDPER_PLAYER_URL", "https://ddper.ir/players/fxi#gores").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6384557276"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Add it in Railway Variables.")

MENU = ReplyKeyboardMarkup(
    [["📊 آمار بازیکن FXI", "🔎 جستجوی بازیکن"], ["🌐 باز کردن پروفایل", "ℹ️ راهنما"]],
    resize_keyboard=True,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DDPERPlayerBot/1.0; +https://ddper.ir)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def clean_text(value: str) -> str:
    return re.sub(r"\\s+", " ", value or "").strip()


def fetch_player_page(url: str) -> dict:
    """Fetch the public profile page and extract text and useful metadata without logging in."""
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = clean_text(description_tag.get("content", "")) if description_tag else ""

    # Preserve structured data when the site provides it.
    structured = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if raw:
            try:
                structured.append(json.loads(raw))
            except (ValueError, TypeError):
                pass

    # Remove navigation and scripts so the summary focuses on page content.
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = clean_text(main.get_text(" ", strip=True))
    text = text[:10000]

    return {
        "url": url,
        "title": title,
        "description": description,
        "text": text,
        "structured": structured,
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
    }


def format_report(data: dict) -> str:
    parts = ["🎮 <b>گزارش پروفایل DDPER</b>"]
    if data.get("title"):
        parts.append(f"📌 <b>عنوان:</b> {data['title']}")
    if data.get("description"):
        parts.append(f"📝 <b>توضیحات:</b> {data['description']}")
    body = data.get("text", "")
    if body:
        # Avoid repeating a huge navigation dump; show a compact preview.
        body = body[:3200]
        parts.append("📊 <b>اطلاعات صفحه:</b>\n" + body)
    else:
        parts.append("صفحه دریافت شد، اما اطلاعات قابل‌خواندن در HTML پیدا نشد. ممکن است سایت اطلاعات را با JavaScript بارگذاری کند.")
    parts.append(f'🔗 <a href="{data["url"]}">مشاهده پروفایل در سایت</a>')
    return "\n\n".join(parts)


async def send_profile(update: Update, url: str, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.effective_message.reply_text("⏳ دارم اطلاعات عمومی پروفایل را از DDPER دریافت می‌کنم…")
    try:
        data = await asyncio.to_thread(fetch_player_page, url)
        report = format_report(data)
        # Telegram has a 4096 character message limit.
        if len(report) > 3900:
            report = report[:3850] + "\n\n…\n🔗 " + url
        await msg.edit_text(report, parse_mode="HTML", disable_web_page_preview=True)
    except requests.RequestException as exc:
        log.warning("DDPER request failed: %s", type(exc).__name__)
        await msg.edit_text(
            "⚠️ الان نتونستم اطلاعات را از DDPER دریافت کنم. ممکن است سایت موقتاً در دسترس نباشد یا درخواست‌های خودکار را محدود کرده باشد.\n\n"
            f'🔗 <a href="{url}">باز کردن پروفایل FXI</a>',
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Unexpected profile parsing error")
        await msg.edit_text("⚠️ هنگام خواندن اطلاعات صفحه مشکلی پیش آمد. کمی بعد دوباره امتحان کن.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "سلام! 👋\nمن ربات نمایش اطلاعات بازیکن DDPER هستم.\n\n"
        "از منو آمار پروفایل FXI را بگیر یا نام بازیکن دیگری را برای جست‌وجو بفرست. "
        "اطلاعاتی که نمایش می‌دهم فقط از صفحه عمومی سایت خوانده می‌شود.",
        reply_markup=MENU,
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_profile(update, PLAYER_URL, context)


async def search_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            "نام بازیکن را این‌طور بفرست:\n/player fxi\n\n"
            "فعلاً لینک پروفایل FXI تنظیم شده است؛ برای نام‌های دیگر باید مسیر پروفایل سایت مشخص باشد."
        )
        return
    player = " ".join(args).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", player):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست. فقط حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط مجاز است.")
        return
    url = f"https://ddper.ir/players/{player}#gores"
    await send_profile(update, url, context)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    if text == "📊 آمار بازیکن FXI":
        await profile(update, context)
    elif text == "🔎 جستجوی بازیکن":
        await update.effective_message.reply_text("نام بازیکن را بفرست یا از دستور /player NAME استفاده کن. نمونه: /player fxi")
    elif text == "🌐 باز کردن پروفایل":
        await update.effective_message.reply_text(f"🔗 پروفایل FXI در DDPER:\n{PLAYER_URL}", reply_markup=MENU)
    elif text == "ℹ️ راهنما":
        await update.effective_message.reply_text(
            "📚 راهنما\n/start — شروع\n/profile — نمایش اطلاعات FXI\n/player NAME — خواندن پروفایل بازیکن\n\n"
            "ربات فقط داده‌های عمومی صفحه را می‌خواند و به حساب کاربری یا اطلاعات خصوصی دسترسی ندارد.",
            reply_markup=MENU,
        )
    else:
        await update.effective_message.reply_text("برای دیدن اطلاعات از گزینه «📊 آمار بازیکن FXI» استفاده کن یا /profile را بفرست.", reply_markup=MENU)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("player", search_player))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    log.info("DDPER player bot starting")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
