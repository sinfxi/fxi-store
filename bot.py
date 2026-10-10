import asyncio
import logging
import os
import random
import time
from urllib.parse import quote_plus
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from study_engine import ensure_study_schema, mark_activity, save_card_review, user_dashboard, update_goal, update_profile, due_card

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("darsyar")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "./data/studybot.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
dp = Dispatcher()
last_request: dict[int, float] = {}
awaiting_study_search: set[int] = set()
last_tutor_question: dict[int, str] = {}
timer_tasks: dict[int, asyncio.Task] = {}
openai_client = None

QUESTIONS = [
    {"q": "حاصل ۳ × (۴ + ۲) چیست؟", "options": ["۱۸", "۱۴", "۲۰", "۱۰"], "answer": 0, "why": "ابتدا پرانتز: ۴+۲=۶؛ سپس ۳×۶=۱۸."},
    {"q": "کدام سیاره به خورشید نزدیک‌تر است؟", "options": ["زمین", "زهره", "عطارد", "مریخ"], "answer": 2, "why": "عطارد نزدیک‌ترین سیاره به خورشید است."},
    {"q": "واحد اصلی اندازه‌گیری نیرو در SI چیست؟", "options": ["ژول", "نیوتن", "وات", "پاسکال"], "answer": 1, "why": "نیرو در دستگاه SI با نیوتن (N) اندازه‌گیری می‌شود."},
    {"q": "در جمله‌ی «دانش‌آموز کتاب را خواند»، فعل کدام است؟", "options": ["دانش‌آموز", "کتاب", "را", "خواند"], "answer": 3, "why": "«خواند» کاری را بیان می‌کند که انجام شده است."},
    {"q": "کسر ۱/۲ با کدام عدد اعشاری برابر است؟", "options": ["۰٫۲", "۰٫۵", "۱٫۲", "۲"], "answer": 1, "why": "یک تقسیم بر دو برابر با ۰٫۵ است."},
]
FLASHCARDS = [
    ("ریاضی", "معادله‌ی خطی یک‌مجهولی چیست؟", "معادله‌ای که مجهول در آن توان یک دارد؛ مثلاً ۲x+۳=۹ که جوابش x=۳ است."),
    ("ریاضی", "قانون توزیع‌پذیری چیست؟", "a(b+c)=ab+ac؛ مثال: ۳(۴+۲)=۱۲+۶=۱۸."),
    ("ریاضی", "متمم و مکمل چه تفاوتی دارند؟", "متمم با زاویه جمعاً ۹۰ درجه و مکمل با زاویه جمعاً ۱۸۰ درجه می‌شود."),
    ("ریاضی", "شیب خط چگونه محاسبه می‌شود؟", "برای دو نقطه، شیب برابر تغییر y تقسیم بر تغییر x است: m=(y₂−y₁)/(x₂−x₁)، به شرط x₂≠x₁."),
    ("ریاضی", "قضیه‌ی فیثاغورس چیست؟", "در مثلث قائم‌الزاویه، مربع وتر برابر مجموع مربع دو ضلع دیگر است: a²+b²=c²."),
    ("ریاضی", "احتمال یک پیشامد در حالت‌های هم‌شانس چیست؟", "تعداد حالت‌های مطلوب تقسیم بر تعداد کل حالت‌های ممکن."),
    ("ریاضی", "میانگین حسابی چیست؟", "مجموع داده‌ها تقسیم بر تعداد داده‌ها؛ میانگین ۲، ۴ و ۶ برابر ۴ است."),
    ("ریاضی", "عدد اول چیست؟", "عدد طبیعی بزرگ‌تر از ۱ که فقط دو مقسوم‌علیه مثبت دارد: ۱ و خودش."),
    ("ریاضی", "مساحت دایره چیست؟", "A=πr²؛ در این رابطه r شعاع دایره است."),
    ("ریاضی", "اتحاد مربع دو جمله چیست؟", "(a+b)²=a²+2ab+b² و (a−b)²=a²−2ab+b²."),
    ("فیزیک", "واحد نیرو در SI چیست؟", "نیوتن (N). طبق قانون دوم نیوتن، F=ma."),
    ("فیزیک", "تفاوت جرم و وزن چیست؟", "جرم مقدار ماده و بر حسب کیلوگرم است؛ وزن نیروی گرانش و تقریباً برابر mg است."),
    ("فیزیک", "سرعت متوسط چگونه به دست می‌آید؟", "مسافت کل تقسیم بر زمان کل؛ با جابه‌جایی تقسیم بر زمان، تندی و سرعت برداری را اشتباه نگیریم."),
    ("فیزیک", "قانون دوم نیوتن چیست؟", "برآیند نیرو برابر جرم ضرب‌در شتاب است: F=ma."),
    ("فیزیک", "انرژی جنبشی چیست؟", "انرژی ناشی از حرکت جسم: Ek=½mv²."),
    ("فیزیک", "توان چیست؟", "نرخ انجام کار یا انتقال انرژی در واحد زمان؛ واحد آن وات است."),
    ("فیزیک", "قانون اهم چیست؟", "برای رسانای اهمی در شرایط ثابت، V=IR؛ ولتاژ برابر جریان ضرب‌در مقاومت است."),
    ("فیزیک", "بازتاب نور چیست؟", "برگشت نور از سطح؛ در بازتاب آینه‌ای، زاویه‌ی تابش با زاویه‌ی بازتاب برابر است."),
    ("شیمی", "عدد اتمی چه چیزی را نشان می‌دهد؟", "تعداد پروتون‌های هسته؛ در اتم خنثی با تعداد الکترون‌ها برابر است."),
    ("شیمی", "ایزوتوپ چیست؟", "اتم‌های یک عنصر با تعداد پروتون برابر و تعداد نوترون متفاوت."),
    ("شیمی", "پیوند یونی چگونه شکل می‌گیرد؟", "با انتقال الکترون و جاذبه‌ی الکتریکی بین یون‌های با بار مخالف."),
    ("شیمی", "پیوند کووالانسی چیست؟", "پیوندی که در آن اتم‌ها یک یا چند جفت الکترون را به اشتراک می‌گذارند."),
    ("شیمی", "pH کمتر از ۷ معمولاً چه مفهومی دارد؟", "محلول آبی اسیدی است؛ pH برابر ۷ در دمای مرجع تقریباً خنثی است."),
    ("شیمی", "واکنش‌دهنده و فرآورده چیست؟", "واکنش‌دهنده‌ها مواد آغازین واکنش‌اند و فرآورده‌ها موادی هستند که تولید می‌شوند."),
    ("شیمی", "قانون پایستگی جرم چیست؟", "در واکنش شیمیایی در سامانه‌ی بسته، جرم کل واکنش‌دهنده‌ها با جرم کل فرآورده‌ها برابر می‌ماند."),
    ("شیمی", "کاتالیزگر چه می‌کند؟", "مسیر واکنش با انرژی فعال‌سازی کمتر فراهم می‌کند و در پایان مصرف خالص نمی‌شود."),
    ("زیست‌شناسی", "فتوسنتز چیست؟", "گیاه با انرژی نور، آب و دی‌اکسیدکربن را به مواد آلی تبدیل می‌کند و اکسیژن آزاد می‌شود."),
    ("زیست‌شناسی", "میتوکندری چه نقشی دارد؟", "در تنفس سلولی و تولید بخش بزرگی از ATP موردنیاز سلول نقش دارد."),
    ("زیست‌شناسی", "DNA چیست؟", "مولکول حامل اطلاعات ژنتیکی در جانداران سلولی؛ توالی بازهای آن اطلاعات را رمزگذاری می‌کند."),
    ("زیست‌شناسی", "میتوز چیست؟", "تقسیم هسته که معمولاً دو هسته‌ی دختر با اطلاعات ژنتیکی مشابه ایجاد می‌کند."),
    ("زیست‌شناسی", "میوز چه اهمیتی دارد؟", "تقسیم کاهشی که تعداد کروموزوم‌ها را نصف می‌کند و در تولید سلول‌های جنسی نقش دارد."),
    ("زیست‌شناسی", "نقش گلبول قرمز چیست؟", "هموگلوبین آن به جابه‌جایی اکسیژن و بخشی از دی‌اکسیدکربن کمک می‌کند."),
    ("زیست‌شناسی", "انتخاب طبیعی چیست؟", "افراد دارای ویژگی‌های وراثتی سازگارتر معمولاً بیشتر زنده می‌مانند و تولیدمثل می‌کنند؛ در نتیجه فراوانی آن ویژگی‌ها ممکن است تغییر کند."),
    ("زمین‌شناسی", "سنگ آذرین چگونه تشکیل می‌شود؟", "از سردشدن و انجماد مواد مذاب؛ سردشدن آهسته درون زمین معمولاً بلورهای درشت‌تری می‌سازد."),
    ("زمین‌شناسی", "چرخه‌ی سنگ چیست؟", "فرایندهای ذوب، سردشدن، هوازدگی، رسوب‌گذاری، تراکم و دگرگونی می‌توانند انواع سنگ را به هم تبدیل کنند."),
    ("زمین‌شناسی", "صفحات تکتونیکی چیستند؟", "بخش‌های بزرگ سنگ‌کره که روی سست‌کره حرکت می‌کنند و در زمین‌لرزه، آتشفشان و کوه‌زایی نقش دارند."),
    ("علوم", "تغییر فیزیکی چیست؟", "تغییری که ماده‌ی جدیدی تولید نمی‌کند؛ مانند خردشدن یا ذوب‌شدن یخ."),
    ("علوم", "تغییر شیمیایی چیست؟", "تغییری که یک یا چند ماده‌ی جدید تشکیل می‌شود؛ مانند زنگ‌زدن آهن."),
    ("علوم", "چرا فصل‌ها به وجود می‌آیند؟", "به‌دلیل انحراف محور زمین و گردش آن به دور خورشید، زاویه و مدت تابش در نیم‌کره‌ها تغییر می‌کند."),
    ("فارسی", "نهاد جمله چیست؟", "بخشی که درباره‌اش خبری می‌دهیم؛ در «سارا کتاب خواند»، سارا نهاد است."),
    ("فارسی", "فعل چه چیزی را بیان می‌کند؟", "کار یا حالت را همراه با اطلاعاتی مانند زمان و شخص بیان می‌کند."),
    ("فارسی", "صفت چیست؟", "واژه‌ای که ویژگی اسم را بیان می‌کند؛ مانند «کتابِ مفید»."),
    ("فارسی", "آرایه‌ی تشبیه چیست؟", "مانندکردن چیزی به چیز دیگر با وجه شبه؛ گاهی با واژه‌هایی چون مثل، مانند و چون."),
    ("فارسی", "تضاد در ادبیات چیست؟", "آوردن واژه‌ها یا مفهوم‌های مخالف در کنار هم؛ مانند شب و روز."),
    ("فارسی", "مترادف و متضاد چه تفاوتی دارند؟", "مترادف‌ها معنی یکسان یا نزدیک دارند؛ متضادها معنی مخالف دارند."),
    ("نگارش", "پاراگراف خوب چه ویژگی‌هایی دارد؟", "یک ایده‌ی اصلی روشن، جمله‌های پشتیبان مرتبط و پیوند منطقی بین جمله‌ها."),
    ("نگارش", "چرا بازخوانی متن مهم است؟", "برای اصلاح املا، نشانه‌گذاری، انسجام، تکرارهای غیرضروری و روشن‌ترشدن منظور."),
    ("عربی", "فعل ماضی چه زمانی را نشان می‌دهد؟", "معمولاً کاری را که در گذشته انجام شده است؛ مانند «کَتَبَ» یعنی نوشت."),
    ("عربی", "فعل مضارع چه زمانی را نشان می‌دهد؟", "معمولاً حال یا آینده را؛ مانند «یَکتُبُ» یعنی می‌نویسد/خواهد نوشت، بسته به بافت."),
    ("عربی", "اسم مثنی چیست؟", "اسمی که بر دو فرد یا دو چیز دلالت می‌کند؛ نشانه‌های آن بسته به حالت نحوی تغییر می‌کند."),
    ("عربی", "فاعل در جمله‌ی فعلیه چیست؟", "کسی یا چیزی که کار به او نسبت داده می‌شود و معمولاً پس از فعل می‌آید."),
    ("انگلیسی", "گذشته‌ی ساده‌ی go چیست؟", "went؛ مثال: I went home yesterday."),
    ("انگلیسی", "حال ساده چه کاربردی دارد؟", "برای عادت‌ها، واقعیت‌های عمومی و برنامه‌های ثابت؛ مانند She studies every day."),
    ("انگلیسی", "تفاوت much و many چیست؟", "much معمولاً با اسم‌های غیرقابل‌شمارش و many با اسم‌های قابل‌شمارش جمع می‌آید."),
    ("انگلیسی", "because چه معنی دارد؟", "«چون/زیرا» و برای معرفی دلیل استفاده می‌شود."),
    ("انگلیسی", "صفت تفضیلی چیست؟", "برای مقایسه‌ی دو مورد؛ مثلاً taller یعنی بلندقدتر. شکل درست به نوع صفت بستگی دارد."),
    ("تاریخ", "منبع دست‌اول تاریخی چیست؟", "مدرکی هم‌زمان با رویداد یا ساخته‌شده توسط شاهد/عامل نزدیک به آن، مانند نامه یا سند اصلی."),
    ("تاریخ", "چرا باید منابع تاریخی را مقایسه کرد؟", "برای سنجش سوگیری، تفاوت روایت‌ها، زمینه‌ی تولید منبع و نزدیک‌شدن به برداشت مستندتر."),
    ("جغرافیا", "عرض جغرافیایی چیست؟", "فاصله‌ی زاویه‌ای یک مکان از استوا به سمت شمال یا جنوب."),
    ("جغرافیا", "طول جغرافیایی چیست؟", "فاصله‌ی زاویه‌ای شرق یا غرب نصف‌النهار مبدأ."),
    ("جغرافیا", "هوا و اقلیم چه تفاوتی دارند؟", "هوا وضعیت کوتاه‌مدت جو است؛ اقلیم الگوهای آماری بلندمدت شرایط جوی یک منطقه است."),
    ("جامعه‌شناسی", "هنجار اجتماعی چیست؟", "قاعده یا انتظار مشترکی که رفتار مناسب در یک موقعیت را مشخص می‌کند."),
    ("جامعه‌شناسی", "جامعه‌پذیری چیست؟", "فرایندی که فرد از طریق آن ارزش‌ها، هنجارها و نقش‌های اجتماعی را می‌آموزد."),
    ("اقتصاد", "هزینه‌ی فرصت چیست؟", "ارزش بهترین گزینه‌ای که با انتخاب گزینه‌ی دیگر از دست می‌دهیم."),
    ("اقتصاد", "عرضه و تقاضا چه نقشی در بازار دارند؟", "تعامل آن‌ها بر قیمت و مقدار مبادله اثر می‌گذارد؛ عوامل دیگر هم می‌توانند بازار را تغییر دهند."),
    ("اقتصاد", "تورم چیست؟", "افزایش پایدار سطح عمومی قیمت‌ها در طول زمان، نه صرفاً گران‌شدن یک کالای خاص."),
    ("فلسفه و منطق", "مقدمه و نتیجه در استدلال چیست؟", "مقدمه‌ها دلیل‌هایی هستند که ارائه می‌شوند؛ نتیجه گزاره‌ای است که قرار است از آن‌ها پشتیبانی شود."),
    ("فلسفه و منطق", "مغالطه چیست؟", "خطای استدلالی که ممکن است ظاهر قانع‌کننده داشته باشد اما پشتیبانی منطقی کافی فراهم نکند."),
    ("روان‌شناسی", "حافظه‌ی فعال چیست؟", "سامانه‌ای محدود برای نگه‌داری و پردازش موقت اطلاعات هنگام انجام یک کار ذهنی."),
    ("حسابداری", "معادله‌ی اساسی حسابداری چیست؟", "دارایی‌ها = بدهی‌ها + حقوق مالکانه."),
    ("حسابداری", "دارایی چیست؟", "منبع اقتصادی تحت کنترل واحد تجاری که انتظار می‌رود منافع اقتصادی آینده ایجاد کند."),
    ("حسابداری", "بدهی چیست؟", "تعهد فعلی واحد تجاری برای انتقال منابع اقتصادی در نتیجه‌ی رویدادهای گذشته."),
    ("برنامه‌نویسی", "متغیر چیست؟", "نامی برای ارجاع به داده در برنامه؛ رفتار دقیق آن به زبان برنامه‌نویسی بستگی دارد."),
    ("برنامه‌نویسی", "شرط if چه کاری می‌کند؟", "بخشی از کد را بر اساس درست یا نادرست بودن یک شرط اجرا می‌کند."),
    ("برنامه‌نویسی", "حلقه چیست؟", "ساختاری برای تکرار دستورها تا زمانی که شرط یا تعداد تکرار مشخصی برقرار باشد."),
    ("برنامه‌نویسی", "تابع چیست؟", "بخشی نام‌دار یا قابل‌فراخوانی از برنامه که کاری را انجام می‌دهد و می‌تواند ورودی و خروجی داشته باشد."),
    ("برنامه‌نویسی", "خطای نحوی چیست؟", "نقض قواعد نوشتاری زبان که معمولاً مانع تجزیه یا اجرای درست کد می‌شود."),
    ("شبکه و سخت‌افزار", "IP address چیست؟", "نشانی منطقی برای شناسایی رابط شبکه در یک شبکه‌ی IP."),
    ("شبکه و سخت‌افزار", "RAM چه کاربردی دارد؟", "حافظه‌ی موقت و سریع برای داده‌ها و برنامه‌های در حال استفاده؛ معمولاً با خاموشی برق پاک می‌شود."),
    ("شبکه و سخت‌افزار", "تفاوت SSD و HDD چیست؟", "SSD از حافظه‌ی فلش و بدون قطعات متحرک استفاده می‌کند؛ HDD دیسک چرخان دارد و معمولاً کندتر و ارزان‌تر به‌ازای ظرفیت است."),
    ("برق", "قانون اهم چیست؟", "V=IR برای رسانای اهمی در شرایط ثابت؛ V ولتاژ، I جریان و R مقاومت است."),
    ("برق", "اتصال سری چه ویژگی‌ای دارد؟", "جریان یکسان از همه‌ی اجزا می‌گذرد و ولتاژ منبع بین اجزا تقسیم می‌شود."),
    ("برق", "اتصال موازی چه ویژگی‌ای دارد؟", "اختلاف پتانسیل دو سر شاخه‌ها یکسان است و جریان بین شاخه‌ها تقسیم می‌شود."),
    ("مکانیک", "گشتاور چیست؟", "اثر چرخانندگی نیرو؛ در حالت ساده اندازه‌ی آن برابر نیرو ضرب‌در بازوی عمود نیرو است."),
    ("مکانیک", "اصطکاک چه اثری دارد؟", "در برابر لغزش نسبی یا تمایل به لغزش مقاومت می‌کند؛ می‌تواند حرکت را کم کند یا برای راه‌رفتن ضروری باشد."),
    ("هنر", "ترکیب‌بندی چیست؟", "چگونگی سازمان‌دهی عناصر بصری در اثر برای ایجاد تعادل، تأکید، ریتم و هدایت نگاه."),
    ("هنر", "رنگ‌های مکمل چیستند؟", "جفت‌هایی که در چرخه‌ی رنگ روبه‌روی هم قرار می‌گیرند و کنار هم تضاد بصری زیادی ایجاد می‌کنند."),
    ("سلامت", "چرا استراحت بین دوره‌های مطالعه مفید است؟", "می‌تواند خستگی ذهنی را کم کند و تمرکز را برگرداند؛ مدت مناسب برای افراد و کارها متفاوت است."),
    ("مطالعه", "مرور فعال چیست؟", "به‌جای فقط دوباره‌خوانی، کتاب را ببند و پاسخ را از حافظه بازیابی کن؛ سپس آن را بررسی کن."),
    ("مطالعه", "مرور فاصله‌دار چیست؟", "مرور در چند نوبت با فاصله‌ی زمانی که معمولاً به ماندگاری بهتر کمک می‌کند."),
    ("مطالعه", "وقتی پاسخ فلش‌کارت را بلد نیستم چه کنم؟", "پاسخ را بخوان، با زبان خودت توضیح بده و کارت را در نوبت نزدیک‌تری دوباره مرور کن."),
    ("مطالعه", "روش پومودورو چیست؟", "الگوی رایج: ۲۵ دقیقه تمرکز و ۵ دقیقه استراحت؛ آن را متناسب با نیازت تنظیم کن."),
]

from flashcard_quality import deduplicate_cards
from flashcards_extra import EXTRA_FLASHCARDS
FLASHCARDS = deduplicate_cards(FLASHCARDS + EXTRA_FLASHCARDS)

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 معلم هوشمند", callback_data="menu:tutor"),
         InlineKeyboardButton(text="📝 آزمون ۵ سؤالی", callback_data="menu:exam")],
        [InlineKeyboardButton(text="🧠 آزمون سریع", callback_data="menu:quiz"),
         InlineKeyboardButton(text="🗂 فلش‌کارت", callback_data="menu:cards")],
        [InlineKeyboardButton(text="🎯 چالش روز", callback_data="menu:daily"),
         InlineKeyboardButton(text="📅 برنامه مطالعه", callback_data="menu:plan")],
        [InlineKeyboardButton(text="📘 کمک‌درسی", callback_data="menu:resources"),
         InlineKeyboardButton(text="🔎 جستجوی درسی", callback_data="menu:search")],
        [InlineKeyboardButton(text="📈 پیشرفت من", callback_data="menu:progress"),
         InlineKeyboardButton(text="📖 فرمول‌ها", callback_data="menu:formula")],
        [InlineKeyboardButton(text="🇬🇧 واژه انگلیسی", callback_data="menu:vocab"),
         InlineKeyboardButton(text="⏱ تمرکز", callback_data="menu:focus")],
    ])

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, interactions INTEGER NOT NULL DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS study_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS learning_stats (
            user_id INTEGER PRIMARY KEY,
            quiz_answered INTEGER NOT NULL DEFAULT 0,
            quiz_correct INTEGER NOT NULL DEFAULT 0,
            cards_known INTEGER NOT NULL DEFAULT 0,
            cards_review INTEGER NOT NULL DEFAULT 0
        )""")
        await db.commit()
    await ensure_study_schema()

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
    """Generate a student-friendly explanation; never pretend uncertain facts are certain."""
    global openai_client
    if not OPENAI_API_KEY and not GROQ_API_KEY:
        return (
            "🤖 معلم هوشمند هنوز به کلید سرویس هوش مصنوعی وصل نیست.\n"
            "مدیر باید GROQ_API_KEY یا OPENAI_API_KEY را در Variables ریلوی تنظیم کند.\n\n"
            "تا آن زمان از آزمون‌ها، فلش‌کارت‌ها و جستجوی کمک‌درسی استفاده کن."
        )
    try:
        if openai_client is None:
            from openai import AsyncOpenAI
            if GROQ_API_KEY:
                openai_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            else:
                openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        system_prompt = (
            "تو «درس‌یار»، معلم خصوصی صبور و باهوش برای دانش‌آموزان فارسی‌زبان هستی. "
            "پاسخ را به فارسی روان و متناسب با سن دانش‌آموز بده. "
            "برای مسئله‌ها: ۱) داده‌ها و خواسته را مشخص کن، ۲) روش را توضیح بده، "
            "۳) حل را مرحله‌به‌مرحله انجام بده، ۴) پاسخ نهایی را واضح بنویس، "
            "۵) یک تمرین کوتاه مشابه برای یادگیری عمیق پیشنهاد کن. "
            "برای مفاهیم، تعریف ساده، مثال ملموس و یک جمع‌بندی کوتاه بده. "
            "اگر پایه یا صورت سؤال مبهم است، سؤال روشن‌کننده بپرس. "
            "اطلاعات، فرمول یا منبع ساختگی نساز؛ اگر مطمئن نیستی صادقانه بگو. "
            "به‌جای سرزنش، اشتباه را آرام توضیح بده. متن را مرتب و نه بیش از حد طولانی بنویس. "
            "در موضوعات خطرناک یا غیرآموزشی، ایمنی را رعایت کن."
        )
        response = await openai_client.chat.completions.create(
            model=(GROQ_MODEL if GROQ_API_KEY else OPENAI_MODEL),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question[:3500]},
            ],
            max_tokens=900,
            temperature=0.35,
        )
        answer = (response.choices[0].message.content or "").strip()
        return answer or "پاسخ مناسبی تولید نشد؛ لطفاً سؤال را کمی واضح‌تر بنویس."
    except Exception as exc:
        log.warning("Tutor request failed: %s", type(exc).__name__)
        return "الان در پاسخ‌گویی هوشمند مشکلی پیش آمد. چند لحظه بعد دوباره تلاش کن؛ قابلیت‌های آزمون و فلش‌کارت همچنان در دسترس‌اند."

def tutor_followup_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧩 تمرین مشابه", callback_data="tutor:practice"),
         InlineKeyboardButton(text="📝 خلاصه‌ی ساده", callback_data="tutor:summary")],
        [InlineKeyboardButton(text="❓ سؤال دیگر", callback_data="menu:tutor"),
         InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")],
    ])

async def find_study_results(query: str):
    """Search study-help pages server-side and return readable snippets inside Telegram."""
    import aiohttp
    from bs4 import BeautifulSoup

    search_query = f"({query}) (site:hamyarbook.ir OR site:asan-dars.ir OR site:gama.ir)"
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(search_query)
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DarsYarStudyBot/1.0)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            html = await response.text()
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for item in soup.select(".result"):
        title_el = item.select_one(".result__title")
        snippet_el = item.select_one(".result__snippet")
        if not title_el:
            continue
        title = " ".join(title_el.get_text(" ", strip=True).split())
        snippet = " ".join(snippet_el.get_text(" ", strip=True).split()) if snippet_el else ""
        if title:
            results.append((title[:180], snippet[:500]))
        if len(results) >= 5:
            break
    return results

@dp.message(CommandStart())
async def start_cmd(message: Message):
    user_id = message.from_user.id
    await touch_user(user_id)
    awaiting_study_search.discard(user_id)
    await message.answer(
        "سلام! 👋 به درس‌یار خوش اومدی.\n\n"
        "من کمکت می‌کنم درس‌ها رو بهتر بفهمی، تمرین کنی و پیشرفتت رو دنبال کنی.\n"
        "از منو یکی رو انتخاب کن یا همین‌جا سؤال درسی‌ات رو بنویس.\n\n"
        "💡 برای جواب دقیق‌تر، پایه و نام درس رو هم بنویس. "
        "پاسخ‌های هوش مصنوعی رو با کتاب درسی بررسی کن.",
        reply_markup=main_keyboard()
    )

@dp.message(Command("resources"))
async def resources_cmd(message: Message):
    awaiting_study_search.add(message.from_user.id)
    await message.answer(
        "📘 کمک‌درسی\n\n"
        "سؤال یا موضوع درسی‌ات را همین‌جا بنویس. نتیجه‌ها داخل ربات نمایش داده می‌شوند.\n"
        "برای شروع، فقط متن سؤال را بفرست."
    )

@dp.message(Command("search"))
async def resource_search_cmd(message: Message):
    query = (message.text or "").partition(" ")[2].strip()
    if not query:
        awaiting_study_search.add(message.from_user.id)
        await message.answer("سؤال یا موضوع درسی را همین‌جا بنویس:")
        return
    await perform_study_search(message, query)

async def perform_study_search(message: Message, query: str):
    awaiting_study_search.discard(message.from_user.id)
    status = await message.answer("🔎 دارم جواب‌ها و تمرین‌های مرتبط را پیدا می‌کنم…")
    try:
        results = await find_study_results(query)
    except Exception as exc:
        log.warning("Study search failed: %s", type(exc).__name__)
        await status.edit_text(
            "الان جستجوی آنلاین در دسترس نیست. دوباره تلاش کن یا متن سؤال را برای توضیح بفرست."
        )
        return
    if not results:
        await status.edit_text(
            f"برای «{query}» نتیجه‌ی مناسبی پیدا نکردم.\n\n"
            "می‌توانی سؤال را دقیق‌تر بنویسی یا با دکمه‌ی «جستجوی سؤال دیگر» دوباره تلاش کنی.",
            reply_markup=study_search_again_keyboard(),
        )
        return
    body = [f"📘 نتیجه‌های درسی برای: {query}"]
    for i, (title, snippet) in enumerate(results, 1):
        body.append(f"\n{i}. {title}" + (f"\n{snippet}" if snippet else ""))
    body.append("\n\nاگر پاسخ کامل نبود، می‌توانی متن سؤال را بفرستی یا جستجوی دیگری انجام بدهی.")
    await status.edit_text(
        "\n".join(body)[:4000],
        reply_markup=study_search_again_keyboard(),
        disable_web_page_preview=True,
    )

def study_search_again_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 جستجوی سؤال دیگر", callback_data="study:again")],
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")],
    ])

@dp.message(F.text & ~F.text.startswith("/"))
async def plain_text_handler(message: Message):
    user_id = message.from_user.id
    question = (message.text or "").strip()
    if not question:
        return
    if user_id in awaiting_study_search:
        if rate_limited(user_id):
            await message.answer("یک لحظه صبر کن و دوباره بفرست 🙂")
            return
        await touch_user(user_id)
        await perform_study_search(message, question)
        return
    if len(question) < 4:
        await message.answer("سؤالت را کمی کامل‌تر بنویس تا بهتر کمک کنم 🙂", reply_markup=main_keyboard())
        return
    if rate_limited(user_id):
        await message.answer("یک لحظه صبر کن و دوباره بفرست 🙂")
        return
    await touch_user(user_id)
    last_tutor_question[user_id] = question
    status = await message.answer("🤖 دارم سؤال را مرحله‌به‌مرحله بررسی می‌کنم…")
    answer = await answer_question(question)
    await status.edit_text(answer[:4000], reply_markup=tutor_followup_keyboard())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📚 راهنمای پیشرفته درس‌یار\n\n"
        "/ask سوال — توضیح مرحله‌ای (با کلید اختیاری هوش مصنوعی)\n"
        "/quiz — آزمون چهارگزینه‌ای فوری\n"
        "/exam — آزمون ۵ سؤالی با امتیاز نهایی\n"
        "/daily — چالش روزانه\n"
        "/flashcards [نام درس] — فلش‌کارت و خودسنجی\n"
        "/formula — برگه فرمول‌های مهم\n"
        "/vocab — تمرین واژگان انگلیسی\n"
        "/plan — برنامه پیشنهادی مطالعه\n"
        "/schedule 120 — برنامه‌ریزی برای زمان دلخواه (دقیقه)\n"
        "/focus — روش تمرکز ۲۵/۵ دقیقه‌ای\n"
        "/progress — گزارش پیشرفت یادگیری\n"
        "/profile پایه هشتم — ثبت مقطع تحصیلی\n"
        "/goal 45 — تعیین هدف مطالعه روزانه به دقیقه\n"
        "/done 25 — ثبت یک جلسه مطالعه و زمان آن\n"
        "/streak — زنجیره مطالعه و هدف امروز\n"
        "/review — مرور فلش‌کارت‌های سررسیدشده\n"
        "/note متن — ذخیره یادداشت درسی شخصی\n"
        "/notes — نمایش یادداشت‌های اخیر\n"
        "/deletenote شماره — حذف یادداشت خودت\n"
        "/timer 25 — تایمر مطالعه به دقیقه\n"
        "/stoptimer — توقف تایمر فعال\n"
        "/tip — نکته تصادفی برای بهتر درس خواندن\n"
        "/resources — جستجوی کمک‌درسی داخل ربات\n"
        "/search عبارت — پیدا کردن نتیجه‌های درسی داخل ربات\n"
        "/privacy — اطلاعات حریم خصوصی\n"
        "/stats — آمار ربات (فقط مدیر)"
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

answered_quiz_messages: set[tuple[int, int, int]] = set()

@dp.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(callback: CallbackQuery):
    try:
        _, q_index_raw, chosen_raw = callback.data.split(":")
        q_index, chosen = int(q_index_raw), int(chosen_raw)
        if not 0 <= q_index < len(QUESTIONS):
            raise ValueError("question index out of range")
        q = QUESTIONS[q_index]
        if not 0 <= chosen < len(q["options"]):
            raise ValueError("answer index out of range")
    except (ValueError, AttributeError):
        await callback.answer("این گزینه معتبر نیست؛ یک آزمون تازه شروع کن.", show_alert=True)
        return

    message_key = (callback.from_user.id, callback.message.chat.id, callback.message.message_id)
    if message_key in answered_quiz_messages:
        await callback.answer("این سؤال قبلاً پاسخ داده شده است.", show_alert=True)
        return
    answered_quiz_messages.add(message_key)
    if len(answered_quiz_messages) > 5000:
        answered_quiz_messages.clear()
        answered_quiz_messages.add(message_key)

    correct = chosen == q["answer"]
    await record_learning(callback.from_user.id, "quiz", correct)
    await callback.answer("آفرین! پاسخ درست بود 🎉" if correct else "این بار نشد؛ با هم مرور کنیم.")
    try:
        await callback.message.edit_text(
            ("✅ درست است!" if correct else f"❌ پاسخ درست: {q['options'][q['answer']]}") +
            f"\n\n📘 توضیح: {q['why']}"
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


# --- Extra learning features ---
exam_sessions: dict[int, dict] = {}
vocab = [
    ("achieve", "به دست آوردن", "She worked hard to achieve her goal."),
    ("although", "اگرچه", "Although it was late, he kept studying."),
    ("compare", "مقایسه کردن", "Compare the two answers carefully."),
    ("improve", "بهبود دادن", "Daily practice can improve your English."),
    ("environment", "محیط زیست / محیط", "We should protect the environment."),
    ("knowledge", "دانش", "Knowledge grows when you ask questions."),
    ("necessary", "ضروری", "Sleep is necessary for learning."),
    ("solution", "راه‌حل", "Try to find a solution before checking the answer."),
]
formulas = [
    # ریاضی عمومی و جبر
    ("ریاضی", "مساحت مستطیل", "طول × عرض"), ("ریاضی", "محیط مستطیل", "2 × (طول + عرض)"),
    ("ریاضی", "مساحت مربع", "ضلع²"), ("ریاضی", "محیط مربع", "4 × ضلع"),
    ("ریاضی", "مساحت مثلث", "½ × قاعده × ارتفاع"), ("ریاضی", "مساحت مثلث با سه ضلع", "√[s(s−a)(s−b)(s−c)] ، s=(a+b+c)/2"),
    ("ریاضی", "مساحت متوازی‌الاضلاع", "قاعده × ارتفاع"), ("ریاضی", "مساحت ذوزنقه", "½ × (قاعدهٔ بزرگ + قاعدهٔ کوچک) × ارتفاع"),
    ("ریاضی", "مساحت لوزی", "½ × قطر اول × قطر دوم"), ("ریاضی", "مساحت دایره", "πr²"),
    ("ریاضی", "محیط دایره", "2πr = πd"), ("ریاضی", "طول کمان", "(θ/360°) × 2πr"),
    ("ریاضی", "مساحت قطاع دایره", "(θ/360°) × πr²"), ("ریاضی", "قضیهٔ فیثاغورس", "a² + b² = c² (در مثلث قائم‌الزاویه)"),
    ("ریاضی", "شیب خط", "m = (y₂−y₁)/(x₂−x₁)"), ("ریاضی", "معادلهٔ خط", "y = mx + b"),
    ("ریاضی", "معادلهٔ درجهٔ اول", "ax + b = 0  ⇒  x = −b/a ، a≠0"),
    ("ریاضی", "معادلهٔ درجهٔ دوم", "ax² + bx + c = 0"),
    ("ریاضی", "فرمول دلتا", "Δ = b² − 4ac"),
    ("ریاضی", "ریشه‌های درجهٔ دوم", "x = (−b ± √Δ)/(2a)"),
    ("ریاضی", "اتحاد مربع مجموع", "(a+b)² = a² + 2ab + b²"),
    ("ریاضی", "اتحاد مربع تفاضل", "(a−b)² = a² − 2ab + b²"),
    ("ریاضی", "اتحاد مزدوج", "(a+b)(a−b) = a² − b²"),
    ("ریاضی", "مکعب مجموع", "(a+b)³ = a³ + 3a²b + 3ab² + b³"),
    ("ریاضی", "مکعب تفاضل", "(a−b)³ = a³ − 3a²b + 3ab² − b³"),
    ("ریاضی", "میانگین حسابی", "مجموع داده‌ها ÷ تعداد داده‌ها"),
    ("ریاضی", "درصد", "(مقدار جزء ÷ مقدار کل) × 100"),
    ("ریاضی", "تناسب", "a/b = c/d  ⇒  ad = bc"),
    ("ریاضی", "توان با پایهٔ یکسان", "aᵐ × aⁿ = aᵐ⁺ⁿ"),
    ("ریاضی", "تقسیم توان‌ها", "aᵐ ÷ aⁿ = aᵐ⁻ⁿ ، a≠0"),
    ("ریاضی", "توانِ توان", "(aᵐ)ⁿ = aᵐⁿ"), ("ریاضی", "توان صفر", "a⁰ = 1 ، a≠0"),
    ("ریاضی", "توان منفی", "a⁻ⁿ = 1/aⁿ ، a≠0"),
    ("ریاضی", "قانون رادیکال", "√(ab) = √a × √b (برای a,b≥0)"),
    ("ریاضی", "جملهٔ nام دنبالهٔ حسابی", "aₙ = a₁ + (n−1)d"),
    ("ریاضی", "مجموع دنبالهٔ حسابی", "Sₙ = n(a₁+aₙ)/2"),
    ("ریاضی", "جملهٔ nام دنبالهٔ هندسی", "aₙ = a₁rⁿ⁻¹"),
    ("ریاضی", "مجموع هندسی متناهی", "Sₙ = a₁(1−rⁿ)/(1−r) ، r≠1"),
    ("ریاضی", "احتمال ساده", "تعداد حالت‌های مطلوب ÷ تعداد حالت‌های هم‌شانس"),
    ("ریاضی", "قانون احتمال متمم", "P(A') = 1 − P(A)"),
    ("ریاضی", "قانون سینوس‌ها", "a/sin A = b/sin B = c/sin C"),
    ("ریاضی", "قانون کسینوس‌ها", "c² = a²+b²−2ab cos C"),
    ("ریاضی", "درجه به رادیان", "رادیان = درجه × π/180"),
    # هندسه و حجم
    ("هندسه", "حجم مکعب", "ضلع³"), ("هندسه", "مساحت کل مکعب", "6 × ضلع²"),
    ("هندسه", "حجم مکعب‌مستطیل", "طول × عرض × ارتفاع"),
    ("هندسه", "حجم منشور", "مساحت قاعده × ارتفاع"),
    ("هندسه", "حجم استوانه", "πr²h"), ("هندسه", "مساحت جانبی استوانه", "2πrh"),
    ("هندسه", "حجم مخروط", "⅓πr²h"), ("هندسه", "حجم هرم", "⅓ × مساحت قاعده × ارتفاع"),
    ("هندسه", "حجم کره", "⁴⁄₃πr³"), ("هندسه", "مساحت سطح کره", "4πr²"),
    ("هندسه", "مجموع زاویه‌های داخلی چندضلعی", "(n−2) × 180°"),
    ("هندسه", "هر زاویهٔ داخلی چندضلعی منتظم", "((n−2) × 180°)/n"),
    ("هندسه", "مجموع زاویه‌های خارجی چندضلعی", "360°"),
    ("هندسه", "طول قطر مربع", "ضلع × √2"),
    # فیزیک
    ("فیزیک", "سرعت متوسط", "جابجایی ÷ زمان (برای تندی متوسط: مسافت کل ÷ زمان کل)"),
    ("فیزیک", "شتاب متوسط", "a = (v₂−v₁)/Δt"), ("فیزیک", "قانون دوم نیوتن", "F = ma"),
    ("فیزیک", "وزن", "W = mg"), ("فیزیک", "تکانه", "p = mv"),
    ("فیزیک", "ضربه", "J = FΔt = Δp (نیروی ثابت)"),
    ("فیزیک", "کار نیروی ثابت", "W = Fd cosθ"), ("فیزیک", "انرژی جنبشی", "K = ½mv²"),
    ("فیزیک", "انرژی پتانسیل گرانشی", "U = mgh (نزدیک سطح زمین)"),
    ("فیزیک", "توان متوسط", "P = W/t"), ("فیزیک", "بازده", "(انرژی یا توان مفید ÷ ورودی) × 100%"),
    ("فیزیک", "چگالی", "ρ = m/V"), ("فیزیک", "فشار", "P = F/A"),
    ("فیزیک", "فشار مایع", "P = ρgh (فشار پیمانه‌ای)"),
    ("فیزیک", "اصل ارشمیدس", "نیروی شناوری = وزن سیال جابه‌جا‌شده"),
    ("فیزیک", "گرما", "Q = mcΔT"), ("فیزیک", "گرمای نهان", "Q = mL"),
    ("فیزیک", "تبدیل دما به کلوین", "T(K) = T(°C) + 273.15"),
    ("فیزیک", "انبساط خطی", "ΔL = αL₀ΔT"),
    ("فیزیک", "قانون اهم", "V = IR"), ("فیزیک", "توان الکتریکی", "P = VI = I²R = V²/R"),
    ("فیزیک", "بار الکتریکی", "Q = It"), ("فیزیک", "مقاومت سری", "Rکل = R₁ + R₂ + …"),
    ("فیزیک", "مقاومت موازی", "1/Rکل = 1/R₁ + 1/R₂ + …"),
    ("فیزیک", "قانون کولن", "F = k|q₁q₂|/r²"),
    ("فیزیک", "میدان الکتریکی", "E = F/q"), ("فیزیک", "انرژی الکتریکی", "E = Pt"),
    ("فیزیک", "قانون بازتاب", "زاویهٔ تابش = زاویهٔ بازتاب"),
    ("فیزیک", "رابطهٔ موج", "v = fλ"), ("فیزیک", "دوره و بسامد", "T = 1/f"),
    ("فیزیک", "سرعت موج", "طول موج × بسامد"),
    ("فیزیک", "قانون هوک", "F = −kx"), ("فیزیک", "انرژی فنر", "U = ½kx²"),
    ("فیزیک", "گرانش نیوتن", "F = Gm₁m₂/r²"),
    ("فیزیک", "حرکت یکنواخت", "x = x₀ + vt"),
    ("فیزیک", "حرکت با شتاب ثابت: سرعت", "v = v₀ + at"),
    ("فیزیک", "حرکت با شتاب ثابت: مکان", "x = x₀ + v₀t + ½at²"),
    ("فیزیک", "معادلهٔ مستقل از زمان", "v² = v₀² + 2aΔx"),
    # شیمی
    ("شیمی", "چگالی", "ρ = m/V"), ("شیمی", "تعداد مول", "n = m/M"),
    ("شیمی", "غلظت مولار", "C = n/V (حجم بر حسب لیتر)"),
    ("شیمی", "تعداد ذره", "N = nNₐ ، Nₐ ≈ 6.022×10²³ mol⁻¹"),
    ("شیمی", "درصد جرمی", "(جرم حل‌شونده ÷ جرم محلول) × 100%"),
    ("شیمی", "رقیق‌سازی محلول", "C₁V₁ = C₂V₂"),
    ("شیمی", "pH", "pH = −log₁₀[H⁺] (تقریب محلول‌های رقیق)"),
    ("شیمی", "pOH", "pOH = −log₁₀[OH⁻]"),
    ("شیمی", "رابطهٔ pH و pOH", "در 25°C برای محلول آبی رقیق: pH + pOH ≈ 14"),
    ("شیمی", "قانون گاز ایده‌آل", "PV = nRT"),
    ("شیمی", "دمای کلوین", "T(K) = T(°C) + 273.15"),
    ("شیمی", "غلظت جرمی", "جرم حل‌شونده ÷ حجم محلول"),
    ("شیمی", "بازده درصدی واکنش", "(مقدار واقعی ÷ مقدار نظری) × 100%"),
    ("شیمی", "درصد خلوص", "(جرم مادهٔ خالص ÷ جرم نمونه) × 100%"),
    ("شیمی", "رابطهٔ مول و ذره", "n = N/Nₐ"),
    ("شیمی", "قانون بقای جرم", "جرم کل واکنش‌دهنده‌ها = جرم کل فرآورده‌ها (در سامانهٔ بسته)"),
    # زیست و آمار
    ("زیست‌شناسی", "بهره‌وری خالص اولیه", "NPP = GPP − تنفس تولیدکنندگان"),
    ("زیست‌شناسی", "بزرگ‌نمایی میکروسکوپ", "بزرگ‌نمایی کل = بزرگ‌نمایی چشمی × بزرگ‌نمایی عدسی شیئی"),
    ("آمار", "میانگین", "x̄ = مجموع داده‌ها ÷ تعداد داده‌ها"),
    ("آمار", "دامنهٔ تغییرات", "بزرگ‌ترین داده − کوچک‌ترین داده"),
    ("آمار", "احتمال متمم", "P(A') = 1 − P(A)"),
    ("آمار", "احتمال اجتماع دو رویداد", "P(A∪B) = P(A)+P(B)−P(A∩B)"),
    ("آمار", "رویدادهای مستقل", "P(A∩B) = P(A)P(B)"),
    # حسابداری
    ("حسابداری", "معادلهٔ اساسی حسابداری", "دارایی = بدهی + حقوق مالکانه"),
    ("حسابداری", "سود خالص", "درآمدها − هزینه‌ها"),
    ("حسابداری", "سرمایهٔ پایان دوره", "سرمایهٔ اول دوره + سرمایه‌گذاری مالک + سود خالص − برداشت"),
    ("حسابداری", "نسبت جاری", "دارایی جاری ÷ بدهی جاری"),
    ("حسابداری", "بهای تمام‌شدهٔ کالای فروش‌رفته", "موجودی اول دوره + خالص خرید − موجودی پایان دوره"),
]
GRADE_FORMULAS = {
1: [("جمع", "a+b=c؛ c−a=b"), ("محیط مربع", "P=4a"), ("محیط مستطیل", "P=2(l+w)")],
2: [("ضرب", "a×b = جمع تکراری"), ("تقسیم", "a×b=c ⇒ c÷a=b"), ("مساحت مستطیل", "A=l×w")],
3: [("مساحت مربع", "A=a²"), ("محیط مستطیل", "P=2(l+w)"), ("کسر", "قسمت‌های انتخابی÷کل قسمت‌های مساوی")],
4: [("جمع کسرهای هم‌مخرج", "a/n+b/n=(a+b)/n"), ("مساحت مستطیل", "A=l×w"), ("محیط چندضلعی", "P=مجموع طول ضلع‌ها")],
5: [("ضرب کسرها", "(a/b)×(c/d)=ac/bd"), ("تقسیم کسرها", "(a/b)÷(c/d)=(a/b)×(d/c)"), ("درصد", "(جزء÷کل)×۱۰۰"), ("حجم مکعب", "V=a³")],
6: [("تناسب", "a/b=c/d ⇒ ad=bc"), ("مساحت مثلث", "A=bh/2"), ("مساحت دایره", "A=πr²"), ("میانگین", "مجموع داده‌ها÷تعداد داده‌ها")],
7: [("توزیع‌پذیری", "a(b+c)=ab+ac"), ("معادله", "x+a=b ⇒ x=b−a"), ("مجموع زاویه‌های مثلث", "A+B+C=۱۸۰°"), ("تناسب مستقیم", "y=kx")],
8: [("مربع مجموع", "(a+b)²=a²+2ab+b²"), ("مربع تفاضل", "(a−b)²=a²−2ab+b²"), ("مزدوج", "(a+b)(a−b)=a²−b²"), ("فیثاغورس", "a²+b²=c²")],
9: [("توان‌های هم‌پایه", "aᵐ×aⁿ=aᵐ⁺ⁿ"), ("تقسیم توان‌ها", "aᵐ÷aⁿ=aᵐ⁻ⁿ"), ("معادلهٔ درجهٔ اول", "ax+b=0 ⇒ x=−b/a"), ("حجم استوانه", "V=πr²h")],
10: [("شیب خط", "m=(y₂−y₁)/(x₂−x₁)"), ("معادلهٔ خط", "y−y₁=m(x−x₁)"), ("نسبت‌های مثلثاتی", "sinθ=مقابل/وتر؛ cosθ=مجاور/وتر"), ("رابطهٔ بنیادی", "sin²θ+cos²θ=1")],
11: [("معادلهٔ درجهٔ دوم", "ax²+bx+c=0"), ("دلتا", "Δ=b²−4ac"), ("ریشه‌ها", "x=(−b±√Δ)/(2a)"), ("دنبالهٔ حسابی", "aₙ=a₁+(n−1)d"), ("مجموع دنباله", "Sₙ=n(a₁+aₙ)/2")],
12: [("مشتق توان", "d(xⁿ)/dx=nxⁿ⁻¹"), ("قاعدهٔ ضرب", "(fg)'=f'g+fg'"), ("قاعدهٔ زنجیره‌ای", "(f(g(x)))'=f'(g(x))g'(x)"), ("انتگرال توان", "∫xⁿdx=xⁿ⁺¹/(n+1)+C، n≠−1"), ("احتمال شرطی", "P(A|B)=P(A∩B)/P(B)")],
}
GRADE_NAMES = {1:"اول",2:"دوم",3:"سوم",4:"چهارم",5:"پنجم",6:"ششم",7:"هفتم",8:"هشتم",9:"نهم",10:"دهم",11:"یازدهم",12:"دوازدهم"}

def format_grade_formula_pages(grade: int):
    entries = GRADE_FORMULAS.get(grade, [])
    lines = [f"📚 فرمول‌های ریاضی پایهٔ {GRADE_NAMES[grade]}", f"تعداد: {len(entries)} رابطه", ""]
    for name, formula in entries:
        lines.extend([f"• {name}", f"  {formula}", ""])
    output = "\n".join(lines).strip()
    return [output[i:i+3200] for i in range(0, len(output), 3200)]

async def record_learning(user_id: int, field: str, correct: bool | None = None):
    await mark_activity(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO learning_stats(user_id) VALUES(?)", (user_id,))
        if field == "quiz":
            await db.execute("UPDATE learning_stats SET quiz_answered=quiz_answered+1, quiz_correct=quiz_correct+? WHERE user_id=?", (1 if correct else 0, user_id))
        elif field == "known":
            await db.execute("UPDATE learning_stats SET cards_known=cards_known+1 WHERE user_id=?", (user_id,))
        elif field == "review":
            await db.execute("UPDATE learning_stats SET cards_review=cards_review+1 WHERE user_id=?", (user_id,))
        await db.commit()

async def send_daily(target):
    q_index = random.randrange(len(QUESTIONS))
    q = QUESTIONS[q_index]
    await target.answer("🎯 چالش روز درس‌یار\n\n" + q["q"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f"quiz:{q_index}:{i}")]
        for i, opt in enumerate(q["options"])
    ]))

@dp.message(Command("daily"))
async def daily_cmd(message: Message):
    await touch_user(message.from_user.id)
    await send_daily(message)

@dp.message(Command("challenge"))
async def challenge_cmd(message: Message):
    await send_daily(message)

@dp.message(Command("exam"))
async def exam_cmd(message: Message):
    await touch_user(message.from_user.id)
    user_id = message.from_user.id
    indices = random.sample(range(len(QUESTIONS)), min(5, len(QUESTIONS)))
    exam_sessions[user_id] = {"indices": indices, "position": 0, "score": 0}
    await send_exam_question(message, user_id)

async def send_exam_question(target, user_id: int):
    session = exam_sessions.get(user_id)
    if not session:
        await target.answer("آزمون فعالی نیست؛ /exam را بزن.")
        return
    q = QUESTIONS[session["indices"][session["position"]]]
    await target.answer(f"📝 آزمون • سؤال {session['position']+1}/5\n\n{q['q']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f"exam:{session['position']}:{i}")]
        for i, opt in enumerate(q["options"])
    ]))

@dp.callback_query(F.data.startswith("exam:"))
async def exam_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = exam_sessions.get(user_id)
    if not session:
        await callback.answer("آزمون تمام شده؛ برای شروع دوباره /exam را بزن.", show_alert=True)
        return
    try:
        _, position_raw, chosen_raw = callback.data.split(":")
        question_position, chosen = int(position_raw), int(chosen_raw)
    except (ValueError, AttributeError):
        await callback.answer("این گزینه معتبر نیست؛ /exam را دوباره بزن.", show_alert=True)
        return
    if question_position != session["position"]:
        await callback.answer("این سؤال قبلاً پاسخ داده شده؛ سؤال فعلی را انتخاب کن.", show_alert=True)
        return
    if not 0 <= session["position"] < len(session["indices"]):
        exam_sessions.pop(user_id, None)
        await callback.answer("آزمون به پایان رسیده؛ /exam را دوباره بزن.", show_alert=True)
        return
    idx = session["indices"][session["position"]]
    q = QUESTIONS[idx]
    if not 0 <= chosen < len(q["options"]):
        await callback.answer("گزینه نامعتبر است.", show_alert=True)
        return
    correct = chosen == q["answer"]
    session["score"] += int(correct)
    await record_learning(user_id, "quiz", correct)
    await callback.answer("درست بود! 🎉" if correct else "پاسخ درست: " + q["options"][q["answer"]])
    session["position"] += 1
    if session["position"] >= len(session["indices"]):
        score = session["score"]
        del exam_sessions[user_id]
        await callback.message.edit_text(f"🏁 آزمون تمام شد!\nامتیاز: {score}/{len(session['indices'])} ({round(score*100/len(session['indices']))}٪)\n" + ("عالی بود! 🌟" if score >= 4 else "اشتباه‌ها فرصت یادگیری‌اند؛ دوباره تمرین کن 💪"))
    else:
        nq = QUESTIONS[session["indices"][session["position"]]]
        await callback.message.edit_text(f"📝 سؤال {session['position']+1}/{len(session['indices'])}\n\n{nq['q']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=opt, callback_data=f"exam:{session['position']}:{i}")]
            for i, opt in enumerate(nq["options"])
        ]))

def format_formula_pages(category: str | None = None):
    selected = [item for item in formulas if not category or item[0].casefold() == category.casefold()]
    if not selected:
        return []
    grouped = {}
    for subject, name, formula in selected:
        grouped.setdefault(subject, []).append((name, formula))
    header = f"📖 بانک فرمول‌ها — {category or 'همهٔ درس‌ها'}\nتعداد: {len(selected)} رابطه\n"
    pages, current = [], header
    for subject, entries in grouped.items():
        current += f"\n【{subject}】\n"
        for name, formula in entries:
            line = f"• {name}\n  {formula}\n"
            if len(current) + len(line) > 3200:
                pages.append(current.rstrip())
                current = f"📖 ادامهٔ بانک فرمول‌ها — {category or 'همهٔ درس‌ها'}\n【{subject}】\n"
            current += line
    if current.strip():
        pages.append(current.rstrip())
    return pages

def formula_categories_text():
    counts = {}
    for subject, _, _ in formulas:
        counts[subject] = counts.get(subject, 0) + 1
    grades = "، ".join(f"{g}: {len(items)} رابطه" for g, items in GRADE_FORMULAS.items())
    return ("📚 بانک فرمول‌ها\nپایه‌های ۱ تا ۱۲: " + grades +
            "\n\nفرمان‌ها: /formula پایه ۷ ، /formula پایه دوازدهم ، /formula فیزیک")

def formula_grade_keyboard():
    rows = []
    for base in range(1, 13, 3):
        rows.append([
            InlineKeyboardButton(text=f"پایهٔ {GRADE_NAMES[g]}", callback_data=f"formula_grade:{g}")
            for g in range(base, min(base + 3, 13))
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def formula_topic_keyboard(grade: int):
    entries = GRADE_FORMULAS.get(grade, [])
    rows = []
    for idx in range(0, len(entries), 2):
        rows.append([
            InlineKeyboardButton(text=entries[i][0][:30], callback_data=f"formula_item:{grade}:{i}")
            for i in range(idx, min(idx + 2, len(entries)))
        ])
    rows.append([InlineKeyboardButton(text="⬅️ انتخاب پایه", callback_data="formula_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(Command("formula"))
async def formula_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip().replace("‌", " ")
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    raw = raw.translate(digits)
    if not raw:
        await message.answer(
            "📚 بانک فرمول‌های درس‌یار\n\n۱) پایهٔ تحصیلی را انتخاب کن.\n۲) مبحث را انتخاب کن.\n۳) ربات همان فرمول را جداگانه نشان می‌دهد.",
            reply_markup=formula_grade_keyboard()
        )
        return
    grade_names = {name: number for number, name in GRADE_NAMES.items()}
    grade_text = raw.removeprefix("پایه").strip()
    grade = int(grade_text) if grade_text.isdigit() and 1 <= int(grade_text) <= 12 else grade_names.get(grade_text)
    if grade:
        await message.answer(f"📘 پایهٔ {GRADE_NAMES[grade]} — یک مبحث را انتخاب کن:", reply_markup=formula_topic_keyboard(grade))
        return
    aliases = {"ریاضی": "ریاضی", "هندسه": "هندسه", "فیزیک": "فیزیک", "شیمی": "شیمی",
               "زیست": "زیست‌شناسی", "زیست‌شناسی": "زیست‌شناسی", "آمار": "آمار",
               "حسابداری": "حسابداری"}
    selected = aliases.get(raw)
    pages = format_formula_pages(selected) if selected else []
    if pages:
        for page in pages:
            await message.answer(page)
    else:
        await message.answer("برای انتخاب دقیق، /formula را بزن و پایه و مبحث را از دکمه‌ها انتخاب کن.")

@dp.callback_query(F.data == "formula_back")
async def formula_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 پایهٔ تحصیلی را انتخاب کن:",
        reply_markup=formula_grade_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("formula_grade:"))
async def formula_grade_selected(callback: CallbackQuery):
    try:
        grade = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("پایه نامعتبر است.", show_alert=True)
        return
    if grade not in GRADE_FORMULAS:
        await callback.answer("این پایه موجود نیست.", show_alert=True)
        return
    await callback.message.edit_text(
        f"📘 پایهٔ {GRADE_NAMES[grade]} — مبحث موردنظر را انتخاب کن:",
        reply_markup=formula_topic_keyboard(grade)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("formula_item:"))
async def formula_item_selected(callback: CallbackQuery):
    try:
        _, grade_raw, item_raw = callback.data.split(":")
        grade, item_index = int(grade_raw), int(item_raw)
        entries = GRADE_FORMULAS[grade]
        name, formula = entries[item_index]
    except (ValueError, IndexError, KeyError):
        await callback.answer("این مبحث در دسترس نیست.", show_alert=True)
        return
    answer = (
        f"📘 پایهٔ {GRADE_NAMES[grade]}\n"
        f"📌 مبحث: {name}\n\n"
        f"🧮 فرمول:\n{formula}\n\n"
        "اگر خواستی مبحث دیگری ببینی، از دکمهٔ زیر استفاده کن."
    )
    await callback.message.edit_text(
        answer,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 مباحث همین پایه", callback_data=f"formula_grade:{grade}")],
            [InlineKeyboardButton(text="🔢 انتخاب پایهٔ دیگر", callback_data="formula_back")]
        ])
    )
    await callback.answer()

@dp.message(Command("vocab"))
async def vocab_cmd(message: Message):
    word, meaning, example = random.choice(vocab)
    await message.answer(f"🇬🇧 واژه تمرینی: {word}\nمعنی: {meaning}\nمثال: {example}\n\nاول معنی را حدس بزن!")

@dp.message(Command("schedule"))
async def schedule_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip()
    try:
        minutes = int(raw) if raw else 90
    except ValueError:
        minutes = 90
    minutes = max(20, min(minutes, 600))
    blocks, remaining, cycle = [], minutes, 1
    while remaining > 0:
        study = min(25, remaining)
        blocks.append(f"{cycle}. 📚 {study} دقیقه تمرکز")
        remaining -= study
        if remaining > 0:
            rest = min(5, remaining)
            blocks.append(f"   ☕ {rest} دقیقه استراحت")
            remaining -= rest
        cycle += 1
    await message.answer(f"🗓 برنامه {minutes} دقیقه‌ای\n\n" + "\n".join(blocks) + "\n\nبرای هر بخش یک هدف مشخص تعیین کن.")

@dp.message(Command("focus"))
async def focus_cmd(message: Message):
    await message.answer("⏱ روش تمرکز درس‌یار\n\n۱) ۲۵ دقیقه فقط یک کار و بدون اعلان\n۲) ۵ دقیقه استراحت و کمی حرکت\n۳) پس از ۴ چرخه، ۱۵ تا ۳۰ دقیقه استراحت طولانی‌تر\n\nاین فرمان تایمر زنده نیست؛ برنامه تمرکز را به تو می‌دهد.")

@dp.message(Command("progress"))
async def progress_cmd(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO learning_stats(user_id) VALUES(?)", (user_id,))
        async with db.execute("SELECT quiz_answered, quiz_correct, cards_known, cards_review FROM learning_stats WHERE user_id=?", (user_id,)) as cur:
            answered, correct, known, review = await cur.fetchone()
    rate = round(correct * 100 / answered) if answered else 0
    await message.answer(f"📈 پیشرفت تو\n\n🧠 پاسخ‌های آزمون: {answered}\n✅ پاسخ درست: {correct} ({rate}٪)\n🗂 کارت‌های بلدم: {known}\n🔁 کارت‌های نیازمند مرور: {review}\n\nهر روز /daily و چند فلش‌کارت انجام بده.")

def card_categories():
    return sorted({card[0] for card in FLASHCARDS})

def category_keyboard():
    categories = card_categories()
    rows = []
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(text=categories[i], callback_data=f"cardsubj:{categories[i]}")]
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(text=categories[i + 1], callback_data=f"cardsubj:{categories[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🎲 همه‌ی درس‌ها", callback_data="cardsubj:همه")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def filtered_card_indices(category: str):
    if not category or category == "همه":
        return list(range(len(FLASHCARDS)))
    return [i for i, card in enumerate(FLASHCARDS) if card[0] == category]

def card_keyboard(idx: int, category: str, revealed: bool = False):
    if not revealed:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👀 نمایش پاسخ", callback_data=f"card:show:{idx}:{category}")],
            [InlineKeyboardButton(text="➡️ کارت بعدی", callback_data=f"card:next:{idx}:{category}")],
            [InlineKeyboardButton(text="📚 انتخاب درس", callback_data="cardsubj:menu")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بلدم", callback_data=f"card:known:{idx}:{category}"),
         InlineKeyboardButton(text="🔁 دوباره مرور کنم", callback_data=f"card:again:{idx}:{category}")],
        [InlineKeyboardButton(text="➡️ کارت بعدی", callback_data=f"card:next:{idx}:{category}")],
        [InlineKeyboardButton(text="📚 انتخاب درس", callback_data="cardsubj:menu")],
    ])

def format_card(idx: int, category: str, revealed: bool = False):
    subject, front, back = FLASHCARDS[idx]
    available = filtered_card_indices(category)
    position = available.index(idx) + 1 if idx in available else 1
    label = "همه‌ی درس‌ها" if category == "همه" else category
    header = f"🗂 فلش‌کارت {position}/{len(available)} • {subject}\n📚 مجموعه: {label}"
    return header + "\n\n" + front + (f"\n\n💡 پاسخ:\n{back}" if revealed else "\n\nقبل از دیدن پاسخ، خودت جواب بده!")

async def send_card(target, category: str = "همه", previous: int | None = None):
    indices = filtered_card_indices(category)
    if not indices:
        await target.answer("برای این درس هنوز کارت آماده نیست.")
        return
    choices = [i for i in indices if i != previous] or indices
    idx = random.choice(choices)
    await target.answer(format_card(idx, category), reply_markup=card_keyboard(idx, category))

@dp.message(Command("flashcards"))
async def cards_cmd(message: Message):
    await touch_user(message.from_user.id)
    query = (message.text or "").partition(" ")[2].strip()
    if query:
        categories = card_categories()
        match = next((cat for cat in categories if cat.casefold() == query.casefold()), None)
        if match:
            await send_card(message, match)
            return
        if query in ("همه", "all"):
            await send_card(message, "همه")
            return
        await message.answer("درس موردنظر را از فهرست انتخاب کن:", reply_markup=category_keyboard())
        return
    await message.answer(
        f"📚 مجموعه‌ی فلش‌کارت درس‌یار\n\nفعلاً {len(FLASHCARDS)} کارت آموزشی در {len(card_categories())} موضوع آماده است.\n"
        "یک موضوع انتخاب کن تا کارت‌های همان درس را مرور کنی:",
        reply_markup=category_keyboard(),
    )

@dp.callback_query(F.data.startswith("cardsubj:"))
async def card_subject_callback(callback: CallbackQuery):
    category = callback.data.partition(":")[2]
    await callback.answer()
    if category == "menu":
        await callback.message.answer("📚 یک درس انتخاب کن:", reply_markup=category_keyboard())
    elif category == "همه":
        await send_card(callback.message, "همه")
    else:
        await send_card(callback.message, category)

@dp.callback_query(F.data.startswith("card:"))
async def card_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]
    idx = int(parts[2])
    category = parts[3] if len(parts) > 3 else "همه"
    if category not in ("همه", *card_categories()):
        category = "همه"
    if action == "next":
        await callback.answer("کارت بعدی آماده شد")
        indices = filtered_card_indices(category)
        choices = [i for i in indices if i != idx] or indices
        next_idx = random.choice(choices)
        await callback.message.edit_text(format_card(next_idx, category), reply_markup=card_keyboard(next_idx, category))
    elif action == "show":
        await callback.answer("پاسخ را با دقت بخوان")
        await callback.message.edit_text(format_card(idx, category, revealed=True), reply_markup=card_keyboard(idx, category, revealed=True))
    elif action in ("known", "again"):
        await record_learning(callback.from_user.id, "known" if action == "known" else "review")
        await save_card_review(callback.from_user.id, idx, action)
        await callback.answer("عالیه، خودسنجی انجام شد! ✅" if action == "known" else "این کارت را دوباره مرور کن 🔁")
        note = "\n\n✅ گفتی این کارت را بلدی." if action == "known" else "\n\n🔁 پیشنهاد: این کارت را در نوبت بعد زودتر مرور کن."
        try:
            await callback.message.edit_text(format_card(idx, category, revealed=True) + note, reply_markup=card_keyboard(idx, category, revealed=True))
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

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
    user_id = callback.from_user.id
    action = callback.data.split(":")[1]
    if action == "quiz":
        q = random.choice(QUESTIONS)
        await callback.message.answer("🧠 آزمون کوتاه\n\n" + q["q"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=opt, callback_data=f"quiz:{QUESTIONS.index(q)}:{i}")]
            for i, opt in enumerate(q["options"])
        ]))
    elif action == "exam":
        indices = random.sample(range(len(QUESTIONS)), min(5, len(QUESTIONS)))
        exam_sessions[user_id] = {"indices": indices, "position": 0, "score": 0}
        await send_exam_question(callback.message, user_id)
    elif action == "cards":
        await callback.message.answer("📚 یک درس انتخاب کن:", reply_markup=category_keyboard())
    elif action in ("resources", "search"):
        awaiting_study_search.add(user_id)
        await callback.message.answer("📘 سؤال یا موضوع درسی‌ات را همین‌جا بنویس؛ نتیجه را داخل ربات می‌بینی.")
    elif action == "tutor":
        awaiting_study_search.discard(user_id)
        await callback.message.answer(
            "🤖 سؤال درسی‌ات را همین‌جا بنویس. می‌توانی پایه و درس را هم اضافه کنی؛ "
            "مثلاً «پایه هشتم، ریاضی: چرا منفی در منفی مثبت می‌شود؟»"
        )
    elif action == "home":
        awaiting_study_search.discard(user_id)
        await callback.message.answer("🏠 منوی درس‌یار:", reply_markup=main_keyboard())
    elif action == "daily":
        await send_daily(callback.message)
    elif action == "progress":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO learning_stats(user_id) VALUES(?)", (user_id,))
            async with db.execute("SELECT quiz_answered, quiz_correct, cards_known, cards_review FROM learning_stats WHERE user_id=?", (user_id,)) as cur:
                answered, correct, known, review = await cur.fetchone()
        rate = round(correct * 100 / answered) if answered else 0
        await callback.message.answer(
            f"📈 پیشرفت تو\n\n🧠 پاسخ‌های آزمون: {answered}\n"
            f"✅ پاسخ درست: {correct} ({rate}٪)\n🗂 کارت‌های بلدم: {known}\n"
            f"🔁 کارت‌های نیازمند مرور: {review}\n\n"
            "نکته: تمرین‌های منظم کوتاه معمولاً از یک جلسه‌ی فشرده‌ی طولانی بهترند.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧠 تمرین آزمون", callback_data="menu:exam"),
                 InlineKeyboardButton(text="🗂 مرور کارت‌ها", callback_data="menu:cards")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")]
            ])
        )
    elif action == "formula":
        pages = format_formula_pages()
        for page in pages:
            await callback.message.answer(page)
        await callback.message.answer(formula_categories_text(), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")]
        ]))
    elif action == "vocab":
        word, meaning, example = random.choice(vocab)
        await callback.message.answer(
            f"🇬🇧 واژه‌ی امروز: {word}\nمعنی: {meaning}\nمثال: {example}\n\n"
            "اول معنی را به یاد بسپار و بعد یک جمله با آن بساز.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 واژه‌ی بعدی", callback_data="menu:vocab")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")]
            ])
        )
    elif action == "focus":
        await callback.message.answer(
            "⏱ روش تمرکز پیشنهادی\n\n۱) ۲۵ دقیقه فقط یک هدف مشخص.\n"
            "۲) ۵ دقیقه استراحت و کمی حرکت.\n۳) پس از چهار دور، استراحت طولانی‌تر.\n\n"
            "گوشی را بی‌صدا کن و قبل از شروع، نتیجه‌ای که می‌خواهی به دست بیاوری بنویس.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 برنامه مطالعه", callback_data="menu:plan")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")]
            ])
        )
    elif action == "plan":
        await callback.message.answer(
            "📅 برنامه‌ی پیشنهادی ۹۰ دقیقه‌ای\n\n"
            "۱) ۲۵ دقیقه: یادگیری یک مبحث کوچک\n۲) ۵ دقیقه: استراحت\n"
            "۳) ۲۵ دقیقه: حل تمرین بدون نگاه به پاسخ\n۴) ۵ دقیقه: استراحت\n"
            "۵) ۲۰ دقیقه: آزمون از خودت\n۶) ۱۰ دقیقه: مرور اشتباه‌ها و نکته‌ها.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱ نکته‌های تمرکز", callback_data="menu:focus")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home")]
            ])
        )
    else:
        await callback.message.answer(
            "🔒 سؤال‌ها برای ساخت گزارش گفت‌وگو ذخیره نمی‌شوند. برای آمار پیشرفت، فقط شمارنده‌های آموزشی نگه‌داری می‌شوند.",
            reply_markup=main_keyboard()
        )

@dp.callback_query(F.data.startswith("tutor:"))
async def tutor_followup(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    original = last_tutor_question.get(user_id)
    if not original:
        await callback.message.answer("اول سؤال درسی‌ات را برایم بنویس.", reply_markup=main_keyboard())
        return
    action = callback.data.split(":")[1]
    if action == "practice":
        prompt = "بر اساس این سؤال، یک تمرین مشابه تازه بساز؛ پاسخ را پنهان کن و فقط سؤال و گزینه‌ها (اگر لازم است) را بده. سؤال اصلی: " + original
    elif action == "summary":
        prompt = "این موضوع را در حداکثر ۵ نکته‌ی ساده و مناسب دانش‌آموز خلاصه کن و یک اشتباه رایج را هم بگو: " + original
    else:
        await callback.message.answer("سؤال بعدی را بنویس.", reply_markup=main_keyboard())
        return
    status = await callback.message.answer("🧠 آماده می‌کنم…")
    answer = await answer_question(prompt)
    await status.edit_text(answer[:4000], reply_markup=tutor_followup_keyboard())

@dp.callback_query(F.data == "study:again")
async def study_search_again(callback: CallbackQuery):
    awaiting_study_search.add(callback.from_user.id)
    await callback.answer()
    await callback.message.answer("سؤال بعدی را بنویس؛ آماده‌ام 🔎")

@dp.message(Command("profile"))
async def profile_cmd(message: Message):
    user_id = message.from_user.id
    raw = (message.text or "").partition(" ")[2].strip()
    grade, goal = await update_profile(user_id, raw if raw else None)
    if raw:
        await message.answer(f"✅ پایه/مقطع ذخیره شد: {raw[:40]}\nهدف روزانه: {goal} دقیقه\nاز این به بعد می‌توانی پایه‌ات را همراه سؤال بنویسی.")
    else:
        await message.answer(f"👤 پروفایل آموزشی\nپایه/مقطع: {grade or 'ثبت نشده'}\nهدف روزانه: {goal} دقیقه\n\nبرای ثبت مقطع: /profile پایه نهم")

@dp.message(Command("goal"))
async def goal_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip()
    if not raw:
        dashboard = await user_dashboard(message.from_user.id)
        await message.answer(f"🎯 هدف روزانهٔ فعلی: {dashboard['goal']} دقیقه\nنمونه: /goal 45")
        return
    try:
        minutes = int(raw)
    except ValueError:
        await message.answer("عدد دقیقه را بنویس؛ نمونه: /goal 45")
        return
    goal = await update_goal(message.from_user.id, minutes)
    await message.answer(f"🎯 هدف روزانه تنظیم شد: {goal} دقیقه.\nبعد از مطالعه، /done 25 را بزن تا زمانت ثبت شود.")

@dp.message(Command("done"))
async def done_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip()
    try:
        minutes = int(raw.split()[0]) if raw else 25
    except ValueError:
        minutes = 25
    minutes = max(1, min(minutes, 600))
    await mark_activity(message.from_user.id, minutes)
    dashboard = await user_dashboard(message.from_user.id)
    remaining = max(0, dashboard["goal"] - dashboard["minutes"])
    state = "🎉 هدف امروزت کامل شد!" if remaining == 0 else f"📌 تا هدف امروز {remaining} دقیقه مانده."
    await message.answer(f"✅ {minutes} دقیقه مطالعه ثبت شد.\nامروز: {dashboard['minutes']}/{dashboard['goal']} دقیقه\nجلسه‌های ثبت‌شده: {dashboard['sessions']}\n{state}")

@dp.message(Command("streak"))
async def streak_cmd(message: Message):
    d = await user_dashboard(message.from_user.id)
    await message.answer(f"🔥 زنجیرهٔ مطالعه: {d['streak']} روز\n📚 امروز: {d['minutes']}/{d['goal']} دقیقه\n🗂 کارت‌های سررسید مرور: {d['due']}\n\nپس از هر جلسه /done 25 را بزن؛ استمرار مهم‌تر از یک روز طولانی است.")

@dp.message(Command("review"))
async def review_cmd(message: Message):
    user_id = message.from_user.id
    card_id, count = await due_card(user_id)
    if card_id is None:
        await message.answer("🎉 کارت سررسیدشده‌ای نداری. چند فلش‌کارت مرور کن؛ پاسخ «بلدم» فاصلهٔ مرور بعدی را به‌تدریج بیشتر می‌کند.", reply_markup=category_keyboard())
        return
    category = FLASHCARDS[card_id][0]
    await message.answer(f"🔁 مرور فاصله‌دار • {count} کارت سررسید شده\n\n" + format_card(card_id, category), reply_markup=card_keyboard(card_id, category))

@dp.message(Command("note"))
async def note_cmd(message: Message):
    user_id = message.from_user.id
    note = (message.text or "").partition(" ")[2].strip()
    if not note:
        await message.answer("📝 برای ذخیره یادداشت بنویس:\n/note نکته مهم فصل دوم")
        return
    if len(note) > 1500:
        await message.answer("یادداشت خیلی طولانی است؛ حداکثر ۱۵۰۰ نویسه بفرست.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO study_notes(user_id, note) VALUES(?, ?)", (user_id, note))
        note_id = cur.lastrowid
        await db.commit()
    await message.answer(f"✅ یادداشت #{note_id} ذخیره شد. فقط خودت می‌توانی یادداشت‌هایت را ببینی.\nبرای دیدن: /notes")


@dp.message(Command("notes"))
async def notes_cmd(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, note, created_at FROM study_notes WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (message.from_user.id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("هنوز یادداشتی ذخیره نکرده‌ای. نمونه: /note تعریف فتوسنتز")
        return
    lines = ["📝 یادداشت‌های اخیر تو (حداکثر ۱۰ مورد):"]
    for note_id, note, created_at in rows:
        lines.append(f"\n#{note_id} • {created_at}\n{note}")
    lines.append("\nبرای حذف یک یادداشت: /deletenote شماره")
    await message.answer("\n".join(lines)[:4000])


@dp.message(Command("deletenote"))
async def delete_note_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip()
    if not raw.isdigit():
        await message.answer("شماره یادداشت را بنویس؛ نمونه: /deletenote 3")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM study_notes WHERE id=? AND user_id=?",
            (int(raw), message.from_user.id)
        )
        await db.commit()
    if cur.rowcount:
        await message.answer("🗑 یادداشت حذف شد.")
    else:
        await message.answer("یادداشت پیدا نشد یا متعلق به تو نیست.")


async def finish_study_timer(user_id: int, chat_id: int, bot, minutes: int):
    try:
        await asyncio.sleep(minutes * 60)
        await bot.send_message(
            chat_id,
            f"⏰ {minutes} دقیقه تمام شد! اگر مطالعه کردی، برای ثبت در آمار /done {minutes} را بزن.\n۵ دقیقه استراحت کوتاه یادت نرود 🌿"
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Study timer notification failed")
    finally:
        current = timer_tasks.get(user_id)
        if current is asyncio.current_task():
            timer_tasks.pop(user_id, None)


@dp.message(Command("timer"))
async def timer_cmd(message: Message):
    raw = (message.text or "").partition(" ")[2].strip()
    try:
        minutes = int(raw) if raw else 25
    except ValueError:
        await message.answer("مدت تایمر را به دقیقه بنویس؛ نمونه: /timer 25")
        return
    if not 1 <= minutes <= 180:
        await message.answer("مدت تایمر باید بین ۱ تا ۱۸۰ دقیقه باشد.")
        return
    user_id = message.from_user.id
    previous = timer_tasks.get(user_id)
    if previous and not previous.done():
        await message.answer("یک تایمر فعال داری. اول /stoptimer را بزن یا صبر کن تمام شود.")
        return
    timer_tasks[user_id] = asyncio.create_task(
        finish_study_timer(user_id, message.chat.id, message.bot, minutes)
    )
    await message.answer(f"⏱ تایمر {minutes} دقیقه‌ای شروع شد.\nوقتی تمام شود به همین گفت‌وگو پیام می‌دهم. برای توقف: /stoptimer")


@dp.message(Command("stoptimer"))
async def stop_timer_cmd(message: Message):
    task = timer_tasks.get(message.from_user.id)
    if not task or task.done():
        await message.answer("تایمر فعالی پیدا نکردم.")
        return
    task.cancel()
    await message.answer("⏹ تایمر متوقف شد.")


STUDY_TIPS = [
    "🧠 بازیابی فعال: کتاب را ببند و نکته‌ها را از حافظه توضیح بده.",
    "🔁 مرور فاصله‌دار: مطلب را امروز، فردا و چند روز بعد دوباره مرور کن.",
    "✍️ تمرین حل‌کردنی: قبل از دیدن پاسخ، خودت راه‌حل را کامل بنویس.",
    "🎯 هدف کوچک: به‌جای «ریاضی بخوانم»، بگو «سه تمرین معادله حل کنم».",
    "📵 تمرکز: برای یک بازه کوتاه اعلان‌ها را خاموش و فقط یک کار را انتخاب کن.",
    "🗣️ روش فاینمن: موضوع را با زبان ساده طوری توضیح بده که یک دوست بفهمد.",
    "🌙 خواب کافی به تثبیت یادگیری کمک می‌کند؛ شب امتحان تمام خواب را حذف نکن.",
    "✅ اشتباه‌ها را ثبت کن و دلیل اشتباه را بنویس؛ فقط جواب درست را حفظ نکن.",
]


@dp.message(Command("tip"))
async def tip_cmd(message: Message):
    await message.answer("💡 نکتهٔ مطالعهٔ امروز\n\n" + random.choice(STUDY_TIPS))


@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ این پنل فقط برای مدیر ربات است.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(interactions),0) FROM users") as cur:
            users, interactions = await cur.fetchone()
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(minutes),0) FROM study_days") as cur:
            active_days, minutes = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) FROM learning_stats") as cur:
            tracked = (await cur.fetchone())[0]
    await message.answer(f"🛠 پنل مدیریت درس‌یار\n\n👥 کاربران ثبت‌شده: {users}\n💬 تعامل‌ها: {interactions}\n📅 روزهای فعال کاربر: {active_days}\n⏱ مجموع دقیقه‌های ثبت‌شده: {minutes}\n📊 کاربران دارای آمار یادگیری: {tracked}\n🗂 فلش‌کارت‌ها: {len(FLASHCARDS)} در {len(card_categories())} موضوع\n🧠 پرسش‌های آزمون: {len(QUESTIONS)}\n\nفرمان‌های مدیریتی: /stats")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in Railway Variables or .env.")
    await init_db()
    bot = Bot(token=BOT_TOKEN)

    # The dashboard shares the bot's persistent SQLite database and runs in the same
    # process, so Railway still has exactly one Telegram polling replica.
    from aiohttp import web
    from web_dashboard import create_web_app
    app = create_web_app(bot, flashcards_count=len(FLASHCARDS), subject_count=len(card_categories()))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("DarsYar web dashboard listening on port %s", port)
    log.info("Starting DarsYar polling bot")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
