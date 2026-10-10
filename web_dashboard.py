"""Authenticated web dashboard for the DarsYar Telegram study bot."""
from __future__ import annotations

import asyncio
import csv
import hmac
import io
import logging
import os
from datetime import date, timedelta

import aiosqlite
from aiohttp import web

DB_PATH = os.getenv("DB_PATH", "./data/studybot.db")
log = logging.getLogger("darsyar.web")


SESSION_COOKIE = "darsyar_session"
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _session_secret() -> str:
    return os.getenv("WEB_SESSION_SECRET", "").strip()


def _session_value(email: str, expires: int) -> str:
    payload = f"{expires}:{email}"
    signature = hmac.new(_session_secret().encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}:{signature}"


def _authorized(request: web.Request) -> bool:
    secret = _session_secret()
    cookie = request.cookies.get(SESSION_COOKIE, "")
    if not secret or not cookie:
        return False
    try:
        expires_raw, email, signature = cookie.split(":", 2)
        expires = int(expires_raw)
    except (ValueError, TypeError):
        return False
    if expires < int(__import__("time").time()):
        return False
    expected = hmac.new(secret.encode(), f"{expires}:{email}".encode(), "sha256").hexdigest()
    return hmac.compare_digest(signature, expected) and hmac.compare_digest(
        email.casefold(), os.getenv("WEB_ADMIN_EMAIL", "").strip().casefold()
    )


def _require_auth(request: web.Request):
    if not os.getenv("WEB_SESSION_SECRET", "").strip() or not os.getenv("WEB_ADMIN_EMAIL", "").strip() or not os.getenv("WEB_ADMIN_PASSWORD", ""):
        raise web.HTTPServiceUnavailable(text="Web login is not configured.")
    if not _authorized(request):
        raise web.HTTPUnauthorized(text="Authentication required.")


async def login(request: web.Request):
    if not all(os.getenv(key, "").strip() for key in ("WEB_ADMIN_EMAIL", "WEB_ADMIN_PASSWORD", "WEB_SESSION_SECRET")):
        raise web.HTTPServiceUnavailable(text="Web login is not configured.")
    remote = request.remote or "unknown"
    now = __import__("time").time()
    attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(remote, []) if now - stamp < 600]
    LOGIN_ATTEMPTS[remote] = attempts
    if len(attempts) >= 8:
        raise web.HTTPTooManyRequests(text="Too many login attempts. Try again in 10 minutes.")
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Expected JSON.")
    email = str(data.get("email", "")).strip()[:254]
    password = str(data.get("password", ""))[:1024]
    correct_email = hmac.compare_digest(email.casefold(), os.getenv("WEB_ADMIN_EMAIL", "").strip().casefold())
    correct_password = hmac.compare_digest(password, os.getenv("WEB_ADMIN_PASSWORD", ""))
    if not (correct_email and correct_password):
        attempts.append(now)
        LOGIN_ATTEMPTS[remote] = attempts
        raise web.HTTPUnauthorized(text="Email or password is incorrect.")
    LOGIN_ATTEMPTS.pop(remote, None)
    expires = int(now) + 8 * 60 * 60
    response = web.json_response({"ok": True, "email": email})
    response.set_cookie(
        SESSION_COOKIE, _session_value(os.getenv("WEB_ADMIN_EMAIL", "").strip(), expires),
        httponly=True, secure=(request.headers.get("X-Forwarded-Proto", "").lower() == "https" or request.secure),
        samesite="Strict", max_age=8 * 60 * 60, path="/",
    )
    return response


async def logout(request: web.Request):
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="Strict")
    return response


HTML = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b1020"><title>پنل مدیریت درس‌یار</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2e;--panel2:#18223a;--line:#293651;--muted:#9ba9c4;--text:#f2f5ff;--blue:#7c9cff;--green:#5ed6b0;--amber:#f7c66a;--red:#ff8b9c}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 85% 0%,#1b2b4a 0,transparent 45%),var(--bg);font-family:Tahoma,"Segoe UI",sans-serif;color:var(--text);min-height:100vh}
main{max-width:1180px;margin:auto;padding:28px 20px 60px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px}.brand{display:flex;gap:12px;align-items:center}.logo{display:grid;place-items:center;width:48px;height:48px;border-radius:16px;background:linear-gradient(145deg,#7c9cff,#6276e9);font-size:24px;box-shadow:0 8px 28px #526fda33}.eyebrow{color:var(--green);font-size:12px;letter-spacing:.3px}.top h1{margin:5px 0;font-size:25px}.muted{color:var(--muted);font-size:13px;line-height:1.8}.status{border:1px solid #245b50;background:#12372f;color:#8ff0d0;border-radius:99px;padding:8px 12px;font-size:12px;white-space:nowrap}
.card{background:linear-gradient(145deg,#141d32,#101729);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 12px 40px #0002}.auth{max-width:480px;margin:70px auto}.auth h2{margin-top:0}.field{display:flex;gap:8px;margin-top:16px}input,textarea{background:#0c1325;border:1px solid #34415e;color:var(--text);border-radius:12px;padding:12px;font:inherit;min-width:0;width:100%;outline:none}input:focus,textarea:focus{border-color:var(--blue)}button{font:inherit;border:0;border-radius:12px;padding:11px 16px;background:var(--blue);color:#0a1020;font-weight:bold;cursor:pointer}button.secondary{background:#24314c;color:var(--text);border:1px solid #394865}button.danger{background:#482331;color:#ffb3c0;border:1px solid #78404e}button:disabled{opacity:.5;cursor:wait}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:16px 0}.metric{padding:18px}.metric .label{color:var(--muted);font-size:13px}.metric .value{font-size:29px;font-weight:700;margin:12px 0 5px}.metric .foot{color:var(--green);font-size:12px}
.section{margin-top:18px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}.section h2{font-size:17px;margin:0}.tools{display:flex;gap:8px;flex-wrap:wrap}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:680px}th,td{text-align:right;border-bottom:1px solid #26334d;padding:13px 10px;font-size:13px}th{color:var(--muted);font-weight:500}tbody tr:hover{background:#ffffff05}.pill{display:inline-block;border:1px solid #355b52;color:#88e8ca;background:#17362f;border-radius:99px;padding:4px 8px;font-size:11px}.bars{display:flex;align-items:end;gap:10px;height:150px;padding-top:12px}.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:7px;min-width:0;height:100%;justify-content:end}.bar{width:min(34px,80%);min-height:3px;border-radius:8px 8px 3px 3px;background:linear-gradient(#9db3ff,#5b75e7)}.bar-label,.bar-val{font-size:10px;color:var(--muted)}.two{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}.notice{padding:12px 14px;border:1px solid #4b4261;background:#201d37;border-radius:12px;color:#c9c3ff;font-size:12px;line-height:1.8}.error{color:#ff9cac;margin-top:12px;font-size:13px}.hidden{display:none!important}.empty{padding:28px;text-align:center;color:var(--muted)}.toast{position:fixed;bottom:18px;left:18px;background:#1d2b43;border:1px solid #3c4e70;padding:12px 16px;border-radius:12px;max-width:90vw;z-index:5}
@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}.top{align-items:flex-start}.status{font-size:11px}}@media(max-width:480px){main{padding:18px 12px}.grid{gap:9px}.metric{padding:14px}.metric .value{font-size:24px}.top h1{font-size:20px}.field{flex-direction:column}.tools button{flex:1}}
</style></head>
<body><main>
<header class="top"><div class="brand"><div class="logo">📘</div><div><div class="eyebrow">DARSYAR • CONTROL CENTER</div><h1>پنل مدیریت درس‌یار</h1><div class="muted">مرکز کنترل ربات و فعالیت‌های آموزشی</div></div></div><div class="status" id="health">● بررسی وضعیت سرویس…</div></header>
<section id="login" class="card auth"><h2>ورود به فضای مدیریت</h2><p class="muted">با ایمیل مدیر و رمز عبور اختصاصی درس‌یار وارد شو.</p><form id="loginForm"><div class="field" style="flex-direction:column"><label for="email">ایمیل مدیر</label><input id="email" type="email" autocomplete="username" required maxlength="254" placeholder="admin@darsyar.local"><label for="password">رمز عبور</label><input id="password" type="password" autocomplete="current-password" required maxlength="1024" placeholder="رمز عبور امن"><button id="loginBtn" type="submit">ورود امن به پنل</button></div></form><div id="loginError" class="error"></div><div class="notice" style="margin-top:18px">نشست ورود امن است و پس از ۸ ساعت منقضی می‌شود. اطلاعات ورود را با کسی به اشتراک نگذار.</div></section>
<section id="app" class="hidden">
<div class="section-head"><div><h2>نمای کلی</h2><div class="muted" id="updated">—</div></div><div class="tools"><button class="secondary" id="refresh">↻ به‌روزرسانی</button><button class="secondary" id="export">خروجی CSV</button><button class="secondary" id="logout">خروج</button></div></div>
<div class="grid">
<div class="card metric"><div class="label">👥 کاربران ثبت‌شده</div><div class="value" id="mUsers">—</div><div class="foot">شناسه‌های ثبت‌شده در ربات</div></div>
<div class="card metric"><div class="label">💬 تعامل‌ها</div><div class="value" id="mInteractions">—</div><div class="foot">مجموع تعامل‌های شمارش‌شده</div></div>
<div class="card metric"><div class="label">⏱ دقیقهٔ مطالعه</div><div class="value" id="mMinutes">—</div><div class="foot">زمان ثبت‌شده توسط کاربران</div></div>
<div class="card metric"><div class="label">🧠 پاسخ‌های آزمون</div><div class="value" id="mQuiz">—</div><div class="foot" id="mAccuracy">دقت: —</div></div>
</div>
<div class="two">
<section class="card section"><div class="section-head"><div><h2>فعالیت مطالعه در ۷ روز اخیر</h2><div class="muted">بر اساس دقیقه‌هایی که کاربران ثبت کرده‌اند</div></div></div><div id="chart" class="bars"></div></section>
<section class="card section"><div class="section-head"><div><h2>وضعیت محتوا</h2></div></div><div class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr));margin:0"><div><div class="muted">فلش‌کارت</div><div class="value" id="mCards">—</div></div><div><div class="muted">موضوع</div><div class="value" id="mSubjects">—</div></div><div><div class="muted">روزهای فعال</div><div class="value" id="mDays">—</div></div><div><div class="muted">کاربران دارای پروفایل</div><div class="value" id="mProfiles">—</div></div></div></section>
</div>
<section class="card section"><div class="section-head"><div><h2>کاربران</h2><div class="muted">فقط داده‌های موجود در پایگاه داده؛ نام و اطلاعات شخصی‌ای که ربات ذخیره نکرده، حدس زده نمی‌شود.</div></div></div><div class="tools" style="margin-bottom:12px"><input id="search" placeholder="جستجو با شناسهٔ تلگرام یا پایه…" aria-label="جستجوی کاربران"><button id="searchBtn">جستجو</button></div><div class="table-wrap"><table><thead><tr><th>شناسهٔ کاربر</th><th>پایه/مقطع</th><th>تعامل‌ها</th><th>دقیقهٔ ثبت‌شده</th><th>پاسخ آزمون</th><th>دقت</th><th>هدف روزانه</th></tr></thead><tbody id="users"></tbody></table></div><div class="section-head" style="margin-top:12px"><div class="muted" id="userCount">—</div><div class="tools"><button class="secondary" id="prev">قبلی</button><button class="secondary" id="next">بعدی</button></div></div></section>
<section class="card section"><div class="section-head"><div><h2>ارسال پیام همگانی</h2><div class="muted">پیام فقط پس از تأیید نهایی ارسال می‌شود. تلگرام ممکن است ارسال به کاربران مسدودکنندهٔ ربات را رد کند.</div></div></div><textarea id="broadcastText" rows="4" maxlength="3500" placeholder="پیام آموزشی یا اطلاعیه را بنویس…"></textarea><div class="section-head" style="margin-top:12px"><div class="muted">پیام را پیش از ارسال بررسی کن؛ ارسال انبوه قابل بازگشت نیست.</div><button class="danger" id="broadcast">ارسال همگانی</button></div><div id="broadcastResult" class="muted"></div></section>
<div class="notice section">یادآوری: این داشبورد از همان SQLite ربات استفاده می‌کند. آمار به‌صورت لحظه‌ای از داده‌های ذخیره‌شده خوانده می‌شود؛ زمان مطالعه فقط زمانی ثبت می‌شود که کاربر از فرمان‌هایی مانند <b>/done</b> استفاده کند.</div>
</section>
</main><div id="toast" class="toast hidden"></div>
<script>
const $=id=>document.getElementById(id);let page=0;const pageSize=20;let searchTerm="";
async function api(path,opts={}){const r=await fetch(path,{credentials:"same-origin",...opts,headers:{...(opts.headers||{})}});if(!r.ok){const t=await r.text();throw new Error(t||("HTTP "+r.status))}return r}
function fmt(n){return Number(n||0).toLocaleString("fa-IR")}
function toast(t){$("toast").textContent=t;$("toast").classList.remove("hidden");setTimeout(()=>$("toast").classList.add("hidden"),3500)}
async function health(){try{const d=await(await fetch("/health")).json();$("health").textContent=d.status==="ok"?"● سرویس فعال":"● وضعیت نامشخص"}catch{$("health").textContent="● سرویس در دسترس نیست"}}
async function login(event){if(event)event.preventDefault();const email=$("email").value.trim();const password=$("password").value;if(!email||!password){$("loginError").textContent="ایمیل و رمز عبور را وارد کن.";return}const b=$("loginBtn");b.disabled=true;try{await api("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});$("password").value="";$("login").classList.add("hidden");$("app").classList.remove("hidden");$("loginError").textContent="";await loadAll()}catch(e){$("loginError").textContent="ورود انجام نشد؛ ایمیل و رمز عبور را بررسی کن."}finally{b.disabled=false}}
async function logout(){try{await api("/api/logout",{method:"POST"})}catch{}$("app").classList.add("hidden");$("login").classList.remove("hidden");$("password").value=""}
async function loadAll(){try{const d=await(await api("/api/summary")).json();$("mUsers").textContent=fmt(d.users);$("mInteractions").textContent=fmt(d.interactions);$("mMinutes").textContent=fmt(d.minutes);$("mQuiz").textContent=fmt(d.quiz_answered);$("mAccuracy").textContent="دقت پاسخ‌ها: "+fmt(d.accuracy)+"٪";$("mCards").textContent=fmt(d.flashcards);$("mSubjects").textContent=fmt(d.subjects);$("mDays").textContent=fmt(d.active_days);$("mProfiles").textContent=fmt(d.profiles);$("updated").textContent="آخرین به‌روزرسانی: "+new Date().toLocaleString("fa-IR");const max=Math.max(1,...d.week.map(x=>x.minutes));$("chart").replaceChildren(...d.week.map(x=>{const c=document.createElement("div");c.className="bar-col";const v=document.createElement("div");v.className="bar-val";v.textContent=fmt(x.minutes);const b=document.createElement("div");b.className="bar";b.style.height=Math.max(3,x.minutes/max*90)+"px";b.title=x.date+" — "+x.minutes+" دقیقه";const l=document.createElement("div");l.className="bar-label";l.textContent=x.label;c.append(v,b,l);return c}));await loadUsers()}catch(e){toast("خطا در دریافت گزارش‌ها: "+e.message);if(e.message.includes("Authentication"))logout()}}
async function loadUsers(){const u=new URLSearchParams({limit:String(pageSize),offset:String(page*pageSize),search:searchTerm});const d=await(await api("/api/users?"+u)).json();const body=$("users");body.replaceChildren();for(const x of d.users){const tr=document.createElement("tr");[x.user_id,x.grade||"ثبت نشده",fmt(x.interactions),fmt(x.minutes),fmt(x.quiz_answered),x.accuracy+"٪",fmt(x.goal)+" دقیقه"].forEach(v=>{const td=document.createElement("td");td.textContent=v;tr.append(td)});body.append(tr)}if(!d.users.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=7;td.className="empty";td.textContent="کاربری با این جستجو پیدا نشد.";tr.append(td);body.append(tr)}$("userCount").textContent="نمایش "+fmt(d.total?Math.min(d.total,page*pageSize+1):0)+" تا "+fmt(Math.min(d.total,(page+1)*pageSize))+" از "+fmt(d.total)+" کاربر";$("prev").disabled=page===0;$("next").disabled=(page+1)*pageSize>=d.total}
async function exportCsv(){try{const r=await api("/api/export.csv");const blob=await r.blob();const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="darsyar-users.csv";a.click();URL.revokeObjectURL(a.href);toast("خروجی CSV آماده شد.")}catch(e){toast("خروجی ناموفق بود: "+e.message)}}
async function broadcast(){const msg=$("broadcastText").value.trim();if(msg.length<2){toast("پیام خیلی کوتاه است.");return}if(!confirm("پیام برای همهٔ کاربران ثبت‌شده ارسال شود؟ این کار قابل بازگشت نیست."))return;const b=$("broadcast");b.disabled=true;$("broadcastResult").textContent="در حال ارسال…";try{const d=await(await api("/api/broadcast",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:msg,confirm:true})})).json();$("broadcastResult").textContent="ارسال پایان یافت؛ موفق: "+fmt(d.sent)+"، ناموفق: "+fmt(d.failed);$("broadcastText").value="";toast("عملیات ارسال تمام شد.")}catch(e){$("broadcastResult").textContent="ارسال ناموفق بود: "+e.message}finally{b.disabled=false}}
$("loginForm").addEventListener("submit",login);$("refresh").onclick=loadAll;$("logout").onclick=logout;$("export").onclick=exportCsv;$("searchBtn").onclick=()=>{page=0;searchTerm=$("search").value.trim();loadUsers()};$("search").addEventListener("keydown",e=>{if(e.key==="Enter")$("searchBtn").click()});$("prev").onclick=()=>{page=Math.max(0,page-1);loadUsers()};$("next").onclick=()=>{page++;loadUsers()};$("broadcast").onclick=broadcast;health()
</script></body></html>"""


async def health(_request: web.Request):
    return web.json_response({"status": "ok", "service": "darsyar", "date": date.today().isoformat()})


async def dashboard(_request: web.Request):
    return web.Response(text=HTML, content_type="text/html", charset="utf-8")


async def summary(request: web.Request):
    _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        async def one(query, args=()):
            async with db.execute(query, args) as cur:
                return (await cur.fetchone())[0]
        users = await one("SELECT COUNT(*) FROM users")
        interactions = await one("SELECT COALESCE(SUM(interactions),0) FROM users")
        minutes = await one("SELECT COALESCE(SUM(minutes),0) FROM study_days")
        active_days = await one("SELECT COUNT(*) FROM study_days WHERE sessions>0")
        profiles = await one("SELECT COUNT(*) FROM user_profiles WHERE grade<>''")
        quiz_answered = await one("SELECT COALESCE(SUM(quiz_answered),0) FROM learning_stats")
        quiz_correct = await one("SELECT COALESCE(SUM(quiz_correct),0) FROM learning_stats")
        cards = await one("SELECT COUNT(*) FROM card_reviews")
        async with db.execute("SELECT study_date,COALESCE(SUM(minutes),0) FROM study_days WHERE study_date>=? GROUP BY study_date ORDER BY study_date", ((date.today()-timedelta(days=6)).isoformat(),)) as cur:
            rows = await cur.fetchall()
    daily = {d: m for d, m in rows}
    week = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        week.append({"date": day.isoformat(), "label": day.strftime("%m/%d"), "minutes": daily.get(day.isoformat(), 0)})
    return web.json_response({
        "users": users, "interactions": interactions, "minutes": minutes, "active_days": active_days,
        "profiles": profiles, "quiz_answered": quiz_answered, "quiz_correct": quiz_correct,
        "accuracy": round(quiz_correct * 100 / quiz_answered) if quiz_answered else 0,
        "flashcards": request.app["flashcards_count"], "subjects": request.app["subject_count"], "week": week,
    })


async def users_list(request: web.Request):
    _require_auth(request)
    try:
        limit = min(100, max(1, int(request.query.get("limit", "20"))))
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid pagination.")
    search = request.query.get("search", "").strip()[:80]
    async with aiosqlite.connect(DB_PATH) as db:
        if search:
            where = "WHERE CAST(u.user_id AS TEXT) LIKE ? OR p.grade LIKE ?"
            args = (f"%{search}%", f"%{search}%")
        else:
            where, args = "", ()
        async with db.execute(f"SELECT COUNT(*) FROM users u LEFT JOIN user_profiles p ON p.user_id=u.user_id {where}", args) as cur:
            total = (await cur.fetchone())[0]
        query = f"""SELECT u.user_id,u.interactions,COALESCE(p.grade,''),COALESCE(p.daily_goal,30),
                    COALESCE((SELECT SUM(minutes) FROM study_days d WHERE d.user_id=u.user_id),0),
                    COALESCE(l.quiz_answered,0),COALESCE(l.quiz_correct,0)
                    FROM users u LEFT JOIN user_profiles p ON p.user_id=u.user_id
                    LEFT JOIN learning_stats l ON l.user_id=u.user_id {where}
                    ORDER BY u.interactions DESC LIMIT ? OFFSET ?"""
        async with db.execute(query, (*args, limit, offset)) as cur:
            rows = await cur.fetchall()
    return web.json_response({"total": total, "users": [
        {"user_id": r[0], "interactions": r[1], "grade": r[2], "goal": r[3], "minutes": r[4],
         "quiz_answered": r[5], "accuracy": round(r[6]*100/r[5]) if r[5] else 0}
        for r in rows
    ]})


async def export_csv(request: web.Request):
    _require_auth(request)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""SELECT u.user_id,COALESCE(p.grade,''),u.interactions,COALESCE(p.daily_goal,30),
            COALESCE((SELECT SUM(minutes) FROM study_days d WHERE d.user_id=u.user_id),0),
            COALESCE(l.quiz_answered,0),COALESCE(l.quiz_correct,0)
            FROM users u LEFT JOIN user_profiles p ON p.user_id=u.user_id
            LEFT JOIN learning_stats l ON l.user_id=u.user_id ORDER BY u.user_id""") as cur:
            rows = await cur.fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "grade", "interactions", "daily_goal_minutes", "study_minutes", "quiz_answered", "quiz_correct"])
    writer.writerows(rows)
    return web.Response(text="\ufeff" + buffer.getvalue(), content_type="text/csv", headers={"Content-Disposition": "attachment; filename=darsyar-users.csv"})


async def broadcast(request: web.Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Expected JSON body.")
    message = str(payload.get("text", "")).strip()
    if payload.get("confirm") is not True:
        raise web.HTTPBadRequest(text="Explicit confirmation is required.")
    if not 2 <= len(message) <= 3500:
        raise web.HTTPBadRequest(text="Message must contain 2-3500 characters.")
    bot = request.app["bot"]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users ORDER BY user_id") as cur:
            user_ids = [row[0] for row in await cur.fetchall()]
    sent = failed = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, message)
            sent += 1
        except Exception as exc:
            failed += 1
            log.info("Broadcast failed for user %s: %s", user_id, type(exc).__name__)
        await asyncio.sleep(0.055)
    return web.json_response({"total": len(user_ids), "sent": sent, "failed": failed})


def create_web_app(bot: object, flashcards_count: int = 0, subject_count: int = 0) -> web.Application:
    app = web.Application(client_max_size=16 * 1024)
    app["bot"] = bot
    app["db_path"] = DB_PATH
    app["flashcards_count"] = flashcards_count
    app["subject_count"] = subject_count
    app.router.add_get("/health", health)
    app.router.add_get("/admin", dashboard)
    app.router.add_get("/dashboard", dashboard)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/summary", summary)
    app.router.add_get("/api/users", users_list)
    app.router.add_get("/api/export.csv", export_csv)
    app.router.add_post("/api/broadcast", broadcast)
    from user_portal import setup_user_portal
    setup_user_portal(app)
    return app
