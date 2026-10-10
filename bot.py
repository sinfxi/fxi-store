import asyncio
import logging
import os
import random
import time
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("darsyar")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6384557276"))
DB_PATH = os.getenv("DB_PATH", "./data/studybot.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
dp = Dispatcher()
last_request: dict[int, float] = {}
openai_client = None

QUESTIONS = [
    {"q": "حاصل ۳ × (۴ + ۲) چیست؟", "options": ["۱۸", "۱۴", "۲۰", "۱۰"], "answer": 0, "why": "ابتدا پرانتز: ۴+۲=۶؛ سپس ۳×۶=۱۸."},
    {"q": "کدام سیاره به خورشید نزدیک‌تر است؟", "options": ["زمین", "زهره", "عطارد", "مریخ"], "answer": 2, "why": "عطارد نزدیک‌ترین سیاره به خورشید است."},
    {"q": "واحد اصلی اندازه‌گیری نیرو در SI چیست؟", "options": ["ژول", "نیوتن", "وات", "پاسکال"], "answer": 1, "why": "نیرو در دستگاه SI با نیوتن (N) اندازه‌گیری می‌شود."},
    {"q": "در جمله‌ی «دانش‌آموز کتاب را خواند»، فعل کدام است؟", "options": ["دانش‌آموز", "کتاب", "را", "خواند"], "answer": 3, "why": "«خواند» کاری را بیان می‌کند که انجام شده است."},
    {"q": "کسر ۱/۲ با کدام عدد اعشاری برابر است؟", "options": ["۰٫۲", "۰٫۵", "۱٫۲", "۲"], "answer": 1, "why": "یک تقسیم بر دو برابر با ۰٫۵ است."},
]
FLASHCARDS = [
    ("فتوسنتز چیست؟", "فرایندی که گیاه با کمک نور، آب و دی‌اکسیدکربن قند می‌سازد و اکسیژن آزاد می‌کند."),
    ("میانگین حسابی چگونه محاسبه می‌شود؟", "مجموع داده‌ها را بر تعداد داده‌ها تقسیم می‌کنیم."),
    ("اسم چیست؟", "واژه‌ای برای نامیدن انسان، جانور، چیز، مکان یا مفهوم."),
    ("سرعت متوسط چیست؟", "مسافت طی‌شده تقسیم بر زمان صرف‌شده؛ در حرکت یکنواخت برابر مسافت بر زمان است."),
    ("متمم یک زاویه چیست؟", "زاویه‌ای که مجموع آن با زاویه‌ی موردنظر ۹۰ درجه باشد."),
]

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 آزمون", callback_data="menu:quiz"),
         InlineKeyboardButton(text="🗂 فلش‌کارت", callback_data="menu:cards")],
        [InlineKeyboardButton(text="📅 برنامه مطالعه", callback_data="menu:plan"),
         InlineKeyboardButton(text="🔒 حریم خصوصی", callback_data="menu:privacy")],
    ])

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, interactions INTEGER NOT NULL DEFAULT 0
        )""")
        await db.commit()

async def touch_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users(user_id, interactions) VALUES(?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET interactions=interactions+1",
            (user_id,),
        )
        await db.commit()

def rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    previous = last_request.get(user_id, 0.0)
    if now - previous < 2.0:
        return True
    last_request[user_id] = now
    return False

async def answer_question(question: str) -> str:
    global openai_client
    if not OPENAI_API_KEY and not GROQ_API_KEY:
        return (
            "برای فعال‌کردن پاسخ هوشمند، مدیر می‌تواند GROQ_API_KEY یا OPENAI_API_KEY را در متغیرهای محیطی تنظیم کند.\n\n"
            "تا آن زمان می‌توانی از /quiz و /flashcards استفاده کنی."
        )
    try:
        if openai_client is None:
            from openai import AsyncOpenAI
            if GROQ_API_KEY:
                openai_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            else:
                openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        response = await openai_client.chat.completions.create(
            model=(GROQ_MODEL if GROQ_API_KEY else OPENAI_MODEL),
            messages=[
                {"role": "system", "content": (
                    "تو درس‌یار، دستیار آموزشی فارسی برای دانش‌آموز هستی. "
                    "به فارسی روان، مهربان و دقیق پاسخ بده. مفهوم را مرحله‌به‌مرحله توضیح بده، "
                    "مثال مناسب بزن و در پایان یک سؤال کوتاه برای سنجش فهم مطرح کن. "
                    "اگر پایه یا درس نامشخص است، فرض‌ها را روشن کن. جواب را جعل نکن."
                )},
                {"role": "user", "content": question[:2500]},
            ],
            max_tokens=700,
            temperature=0.4,
        )
        return (response.choices[0].message.content or "نتوانستم پاسخ آماده کنم.").strip()
    except Exception as exc:
        log.warning("AI request failed: %s", type(exc).__name__)
        return "فعلاً سرویس پاسخ هوشمند در دسترس نیست؛ کمی بعد دوباره امتحان کن."

@dp.message(CommandStart())
async def start(message: Message):
    await touch_user(message.from_user.id)
    await message.answer(
        "سلام! 🌱 من «درس‌یار» هستم؛ برای یادگیری، تمرین و برنامه‌ریزی کنارت هستم.\n\n"
        "از دکمه‌ها استفاده کن یا /help را بزن. برای پرسش درسی بنویس: "
        "/ask چرا فصل‌ها به وجود می‌آیند؟",
        reply_markup=main_keyboard(),
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📚 راهنمای درس‌یار\n"
        "/ask سوال درسی — توضیح مرحله‌ای (نیازمند کلید اختیاری هوش مصنوعی)\n"
        "/quiz — آزمون چهارگزینه‌ای\n"
        "/flashcards — فلش‌کارت‌های مرور\n"
        "/plan — برنامه پیشنهادی مطالعه\n"
        "/privacy — اطلاعات حریم خصوصی\n"
        "/stats — آمار ربات (فقط مدیر)\n\n"
        "برای نتیجه بهتر، درس، پایه و بخشی را که دشوار است بنویس."
    )

@dp.message(Command("ask"))
async def ask_cmd(message: Message):
    if rate_limited(message.from_user.id):
        await message.answer("یک لحظه صبر کن و دوباره بفرست 🙂")
        return
    await touch_user(message.from_user.id)
    question = (message.text or "").partition(" ")[2].strip()
    if not question:
        await message.answer("سؤالت را این‌طور بفرست:\n/ask تفاوت جرم و وزن چیست؟")
        return
    await message.answer("دارم سؤال را بررسی می‌کنم… ⏳")
    await message.answer(await answer_question(question))

@dp.message(Command("quiz"))
async def quiz_cmd(message: Message):
    await touch_user(message.from_user.id)
    q = random.choice(QUESTIONS)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f"quiz:{QUESTIONS.index(q)}:{i}")]
        for i, opt in enumerate(q["options"])
    ])
    await message.answer("🧠 آزمون کوتاه\n\n" + q["q"], reply_markup=keyboard)

@dp.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(callback: CallbackQuery):
    _, q_index, chosen = callback.data.split(":")
    q = QUESTIONS[int(q_index)]
    correct = int(chosen) == q["answer"]
    await callback.answer("آفرین! پاسخ درست بود 🎉" if correct else "این بار نشد؛ با هم مرور کنیم.")
    await callback.message.edit_text(
        ("✅ درست است!" if correct else f"❌ پاسخ درست: {q['options'][q['answer']]}") +
        f"\n\n📘 توضیح: {q['why']}"
    )

@dp.message(Command("flashcards"))
async def cards_cmd(message: Message):
    await touch_user(message.from_user.id)
    front, back = random.choice(FLASHCARDS)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 نمایش پاسخ", callback_data="card:show:" + str(FLASHCARDS.index((front, back))))],
        [InlineKeyboardButton(text="🔄 کارت بعدی", callback_data="card:next")],
    ])
    await message.answer("🗂 فلش‌کارت\n\n" + front, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("card:"))
async def card_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    await callback.answer()
    if parts[1] == "next":
        front, _ = random.choice(FLASHCARDS)
        idx = next(i for i, card in enumerate(FLASHCARDS) if card[0] == front)
        await callback.message.edit_text(
            "🗂 فلش‌کارت\n\n" + front,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👀 نمایش پاسخ", callback_data=f"card:show:{idx}")],
                [InlineKeyboardButton(text="🔄 کارت بعدی", callback_data="card:next")],
            ])
        )
    else:
        idx = int(parts[2])
        front, back = FLASHCARDS[idx]
        await callback.message.edit_text(
            f"🗂 {front}\n\n💡 {back}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 کارت بعدی", callback_data="card:next")]
            ])
        )

@dp.message(Command("plan"))
async def plan_cmd(message: Message):
    await touch_user(message.from_user.id)
    await message.answer(
        "📅 برنامه‌ی پیشنهادی ۹۰ دقیقه‌ای\n\n"
        "۱) ۲۵ دقیقه: مطالعه‌ی یک مبحث کوچک\n"
        "۲) ۵ دقیقه: استراحت کوتاه\n"
        "۳) ۲۵ دقیقه: حل تمرین بدون نگاه به پاسخ\n"
        "۴) ۵ دقیقه: استراحت\n"
        "۵) ۲۰ دقیقه: آزمون از خودت و مرور اشتباه‌ها\n"
        "۶) ۱۰ دقیقه: یادداشت نکته‌های مهم\n\n"
        "برای برنامه‌ی شخصی‌تر، پایه، درس‌ها و زمان آزاد روزانه‌ات را با /ask بفرست."
    )

@dp.message(Command("privacy"))
async def privacy_cmd(message: Message):
    await message.answer(
        "🔒 حریم خصوصی\n"
        "• ربات متن سؤال‌ها را در پایگاه داده ذخیره نمی‌کند.\n"
        "• فقط شناسه‌ی عددی کاربر و شمارنده‌ی تعامل برای آمار پایه نگه‌داری می‌شود.\n"
        "• اگر قابلیت هوش مصنوعی فعال باشد، متن سؤال برای تولید پاسخ به ارائه‌دهنده‌ی مدل ارسال می‌شود.\n"
        "• اطلاعات محرمانه، رمز عبور یا کد ورود نفرست.\n"
        "• مدیر باید از توکن تازه استفاده کند و آن را در متغیرهای محیطی نگه دارد."
    )

@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("این فرمان فقط برای مدیر فعال است.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(interactions), 0) FROM users") as cur:
            users, interactions = await cur.fetchone()
    await message.answer(f"📊 آمار\nکاربران: {users}\nتعامل‌ها: {interactions}")

@dp.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery):
    await callback.answer()
    action = callback.data.split(":")[1]
    if action == "quiz":
        q = random.choice(QUESTIONS)
        await callback.message.answer("🧠 " + q["q"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=opt, callback_data=f"quiz:{QUESTIONS.index(q)}:{i}")]
            for i, opt in enumerate(q["options"])
        ]))
    elif action == "cards":
        front, _ = random.choice(FLASHCARDS)
        idx = next(i for i, card in enumerate(FLASHCARDS) if card[0] == front)
        await callback.message.answer("🗂 " + front, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👀 نمایش پاسخ", callback_data=f"card:show:{idx}")],
            [InlineKeyboardButton(text="🔄 کارت بعدی", callback_data="card:next")],
        ]))
    elif action == "plan":
        await callback.message.answer("برنامه: ۲۵ دقیقه مطالعه، ۵ دقیقه استراحت، ۲۵ دقیقه تمرین، ۵ دقیقه استراحت، ۲۰ دقیقه آزمون و ۱۰ دقیقه مرور.")
    else:
        await callback.message.answer("متن سؤال‌ها ذخیره نمی‌شوند. در صورت فعال بودن هوش مصنوعی، سؤال برای تولید پاسخ به ارائه‌دهنده‌ی مدل فرستاده می‌شود.")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in Railway Variables or .env.")
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    log.info("Starting DarsYar polling bot")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
