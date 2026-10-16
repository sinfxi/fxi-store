import os
import re
import json
import logging
import asyncio
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("ddper-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PLAYER_URL = os.getenv("DDPER_PLAYER_URL", "https://ddper.ir/players/fxi#gores").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Add it in Railway Variables.")

MENU = ReplyKeyboardMarkup(
    [["📊 آمار بازیکن FXI", "🔎 جستجوی بازیکن"], ["🌐 لینک پروفایل", "ℹ️ راهنما"]],
    resize_keyboard=True,
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
}


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def flatten_json(value, prefix="", depth=0):
    """Turn nested API/embedded JSON into readable label/value lines."""
    rows = []
    if depth > 5:
        return rows
    if isinstance(value, dict):
        for key, item in value.items():
            label = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key))
            label = label.replace("_", " ").replace("-", " ").strip().title()
            path = f"{prefix} · {label}" if prefix else label
            if isinstance(item, (dict, list)):
                rows.extend(flatten_json(item, path, depth + 1))
            elif item is not None and str(item).strip():
                rows.append((path, clean_text(item)))
    elif isinstance(value, list):
        for i, item in enumerate(value[:40]):
            if isinstance(item, (dict, list)):
                rows.extend(flatten_json(item, prefix, depth + 1))
            elif item is not None and str(item).strip():
                rows.append((prefix or "مقدار", clean_text(item)))
    return rows


def fetch_player_page(url):
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url.split("#", 1)[0], timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = clean_text(description_tag.get("content", "")) if description_tag else ""

    extracted = []
    # Some sites put profile data in JSON-LD or framework hydration payloads.
    for tag in soup.find_all("script"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        typ = (tag.get("type") or "").lower()
        if "json" in typ or raw.lstrip().startswith(("{", "[")):
            try:
                obj = json.loads(raw)
                extracted.extend(flatten_json(obj))
            except (ValueError, TypeError):
                pass

    # Extract visible server-rendered tables and headings.
    for table in soup.find_all("table"):
        for row in table.find_all("tr")[:120]:
            cells = [clean_text(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if len(cells) >= 2:
                extracted.append((cells[0], " | ".join(cells[1:])))
            elif cells:
                extracted.append(("اطلاعات", cells[0]))

    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    visible = clean_text(main.get_text(" ", strip=True))

    # If the page is a JavaScript app, inspect its same-site JS bundles for API paths,
    # then try only plausible public player/profile endpoints for this requested slug.
    api_rows = []
    slug = urlparse(url).path.rstrip("/").split("/")[-1] or "fxi"
    script_urls = []
    for tag in soup.find_all("script", src=True):
        script_urls.append(urljoin(response.url, tag["src"]))
    # Re-fetching the cleaned soup loses script tags; use the original response HTML instead.
    original_soup = BeautifulSoup(response.text, "html.parser")
    script_urls = [urljoin(response.url, tag["src"]) for tag in original_soup.find_all("script", src=True)]
    api_paths = set()
    for script_url in script_urls[:15]:
        try:
            js = session.get(script_url, timeout=12).text
            for match in re.findall(r"""['"`]([^'"\`]{0,100}(?:/api/|api/|players/|player/|profile|stats)[^'"\`]{0,120})['"`]""", js, re.I):
                candidate = match.replace("\\/", "/")
                if candidate.startswith("/") and len(candidate) < 180:
                    api_paths.add(candidate)
        except requests.RequestException:
            continue

    # Try API routes actually referenced by the site's own JS bundle.
    base = f"{urlparse(response.url).scheme}://{urlparse(response.url).netloc}"
    for path in sorted(api_paths, key=lambda x: (("api" not in x.lower()), len(x)))[:25]:
        candidate = path.replace(":slug", slug).replace(":username", slug).replace("{slug}", slug).replace("{username}", slug).replace("[slug]", slug)
        if any(token in candidate.lower() for token in ("players", "player", "profile", "stats", "api")):
            full = urljoin(base, candidate)
            try:
                api_response = session.get(full, headers={"Accept": "application/json"}, timeout=8)
                if api_response.ok and "json" in api_response.headers.get("content-type", "").lower():
                    obj = api_response.json()
                    found = flatten_json(obj)
                    if found:
                        api_rows.extend(found)
            except (requests.RequestException, ValueError):
                pass

    # De-duplicate while preserving order; avoid returning only menu boilerplate.
    rows, seen = [], set()
    for label, value in api_rows + extracted:
        item = (clean_text(label), clean_text(value))
        if item[0] and item[1] and item not in seen:
            seen.add(item)
            rows.append(item)

    return {
        "url": url,
        "title": title,
        "description": description,
        "visible": visible[:12000],
        "rows": rows[:180],
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
    }


def format_report(data):
    parts = ["🎮 <b>اطلاعات بازیکن DDPER</b>"]
    if data.get("title"):
        parts.append(f"👤 <b>پروفایل:</b> {data['title']}")
    if data.get("description"):
        parts.append(f"📝 {data['description']}")
    rows = data.get("rows", [])
    # Prioritize useful game/stat terms over framework metadata.
    priority = ("rank", "point", "score", "finish", "map", "time", "play", "server", "team", "level", "record", "gores", "player", "name", "date", "country", "total")
    rows = sorted(rows, key=lambda item: (not any(p in item[0].lower() for p in priority), len(item[0])))
    lines = []
    for label, value in rows:
        if label.lower() in ("props", "children", "data", "meta", "head", "script", "style"):
            continue
        line = f"• <b>{label[:80]}:</b> {value[:180]}"
        if line not in lines:
            lines.append(line)
    if lines:
        parts.append("📊 <b>آمار استخراج‌شده:</b>\n" + "\n".join(lines[:45]))
    else:
        visible = data.get("visible", "")
        if visible and len(visible) > 80:
            parts.append("📊 <b>اطلاعات صفحه:</b>\n" + visible[:2200])
        else:
            parts.append(
                "⚠️ صفحه باز شد، اما آمار در HTML معمولی نیست و احتمالاً با JavaScript بارگذاری می‌شود. "
                "برای نمایش آمار واقعی باید API عمومی‌ای که خود سایت استفاده می‌کند شناسایی شود؛ فعلاً داده‌ای را حدس نمی‌زنم."
            )
    parts.append(f'🔗 <a href="{data["url"]}">منبع پروفایل</a>')
    return "\n\n".join(parts)


async def send_profile(update, url, context):
    msg = await update.effective_message.reply_text("⏳ دارم آمار را دریافت و برای نمایش داخل تلگرام آماده می‌کنم…")
    try:
        data = await asyncio.to_thread(fetch_player_page, url)
        report = format_report(data)
        if len(report) > 3900:
            report = report[:3750] + "\n\n…\n" + f'🔗 <a href="{url}">ادامه در سایت</a>'
        await msg.edit_text(report, parse_mode="HTML", disable_web_page_preview=True)
    except requests.RequestException as exc:
        log.warning("DDPER request failed: %s", type(exc).__name__)
        await msg.edit_text(
            "⚠️ نتونستم اطلاعات را از DDPER دریافت کنم؛ ممکن است سایت موقتاً در دسترس نباشد یا درخواست خودکار را محدود کرده باشد.\n\n"
            f'🔗 <a href="{url}">پروفایل FXI</a>',
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception:
        log.exception("Profile extraction failed")
        await msg.edit_text("⚠️ موقع استخراج آمار خطایی رخ داد. لطفاً کمی بعد دوباره امتحان کن.")


async def start(update, context):
    await update.effective_message.reply_text(
        "سلام! 👋\nمن ربات نمایش آمار بازیکنان DDPER هستم.\n"
        "از منو آمار FXI را ببین یا نام بازیکن را جست‌وجو کن. اطلاعات تا جای ممکن داخل همین چت نمایش داده می‌شود.",
        reply_markup=MENU,
    )


async def profile(update, context):
    await send_profile(update, PLAYER_URL, context)


async def search_player(update, context):
    args = context.args
    if not args:
        await update.effective_message.reply_text("نام بازیکن را بفرست: /player fxi")
        return
    player = " ".join(args).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", player):
        await update.effective_message.reply_text("نام بازیکن معتبر نیست؛ از حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط استفاده کن.")
        return
    await send_profile(update, f"https://ddper.ir/players/{player}#gores", context)


async def message_handler(update, context):
    text = (update.effective_message.text or "").strip()
    if text == "📊 آمار بازیکن FXI":
        await profile(update, context)
    elif text == "🔎 جستجوی بازیکن":
        await update.effective_message.reply_text("نام بازیکن را بفرست یا دستور /player NAME را استفاده کن؛ نمونه: /player fxi")
    elif text == "🌐 لینک پروفایل":
        await update.effective_message.reply_text(f"🔗 لینک پروفایل FXI:\n{PLAYER_URL}", reply_markup=MENU)
    elif text == "ℹ️ راهنما":
        await update.effective_message.reply_text(
            "📚 راهنما\n/start — شروع\n/profile — نمایش آمار FXI\n/player NAME — آمار بازیکن دیگر\n\n"
            "ربات اطلاعات عمومی را می‌خواند و آمار ساختگی تولید نمی‌کند.",
            reply_markup=MENU,
        )
    else:
        await update.effective_message.reply_text("برای نمایش آمار، «📊 آمار بازیکن FXI» یا /profile را بزن.", reply_markup=MENU)


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
