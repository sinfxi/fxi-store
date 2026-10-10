"""Self-service study portal for DarsYar users."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import date

import aiosqlite
from aiohttp import web

DB_PATH = os.getenv("DB_PATH", "./data/studybot.db")
COOKIE = "darsyar_user_session"
ATTEMPTS: dict[str, list[float]] = {}

HTML = r"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0b1020"><title>پنل دانش‌آموزی درس‌یار</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131d32;--line:#2a3855;--text:#f2f5ff;--muted:#a2afc8;--blue:#90a7ff;--green:#62d8b4}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 80% 0%,#24375a 0,transparent 42%),var(--bg);color:var(--text);font-family:Tahoma,"Segoe UI",sans-serif}main{max-width:1050px;margin:auto;padding:28px 18px 60px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:22px}.brand{display:flex;gap:12px;align-items:center}.logo{width:48px;height:48px;display:grid;place-items:center;border-radius:16px;background:linear-gradient(145deg,#90a7ff,#687be8);font-size:25px}.eyebrow{font-size:11px;color:var(--green);letter-spacing:1px}.top h1{font-size:23px;margin:5px 0}.muted{color:var(--muted);font-size:13px;line-height:1.8}.card{background:linear-gradient(145deg,#17223a,#111a2d);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:0 12px 36px #0002}.auth{max-width:460px;margin:55px auto}.auth h2{margin-top:0}.field{display:grid;gap:8px;margin-top:14px}label{font-size:13px;color:#d4ddf3}input,textarea{width:100%;min-width:0;background:#0b1324;border:1px solid #34425f;color:var(--text);border-radius:12px;padding:12px;font:inherit;outline:none}input:focus,textarea:focus{border-color:var(--blue)}button{font:inherit;cursor:pointer;border:0;border-radius:12px;padding:11px 15px;background:var(--blue);color:#0b1020;font-weight:bold}button.secondary{background:#263550;border:1px solid #3b4a68;color:var(--text)}button:disabled{opacity:.5}.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:16px 0}.metric{padding:18px}.metric .value{font-size:28px;font-weight:bold;margin:10px 0}.metric .label{font-size:13px;color:var(--muted)}.section{margin-top:16px}.section h2{font-size:17px;margin:0 0 12px}.hidden{display:none!important}.error{color:#ff9cac;font-size:13px;margin-top:12px}.note{padding:12px;border:1px solid #31405e;background:#0d1629;border-radius:12px;margin-top:9px;overflow-wrap:anywhere}.note small{color:var(--muted)}.notice{border:1px solid #4b4261;background:#211e37;color:#d1caff;border-radius:12px;padding:13px;font-size:12px;line-height:1.9}.toast{position:fixed;bottom:18px;left:18px;background:#1d2b43;border:1px solid #3c4e70;padding:12px 16px;border-radius:12px;max-width:90vw}.tabs{display:flex;gap:8px;margin-bottom:16px}.tabs button{flex:1}@media(max-width:650px){.grid{grid-template-columns:1fr}.top{align-items:flex-start}.top h1{font-size:19px}.card{padding:16px}.auth{margin:28px auto}}
</style></head><body><main><header class="top"><div class="brand"><div class="logo">📘</div><div><div class="eyebrow">DARSYAR • STUDENT SPACE</div><h1>پنل دانش‌آموزی درس‌یار</h1><div class="muted">برنامه‌ریزی کن، پیشرفتت را ثبت کن و منظم‌تر درس بخوان.</div></div></div><a href="/admin" style="color:#b9c7ff;font-size:12px">ورود مدیر</a></header>
<section id="auth" class="card auth"><div class="tabs"><button id="tabLogin" type="button">ورود</button><button id="tabRegister" class="secondary" type="button">ساخت حساب</button></div><h2 id="authTitle">خوش برگشتی 👋</h2><p class="muted">برای دیدن برنامه و گزارش شخصی‌ات وارد شو.</p><form id="authForm"><div class="field"><label for="name">نام نمایشی (برای حساب جدید)</label><input id="name" maxlength="60" autocomplete="name" placeholder="مثلاً سارا"><label for="email">ایمیل</label><input id="email" type="email" required maxlength="254" autocomplete="email" placeholder="you@example.com"><label for="password">رمز عبور</label><input id="password" type="password" required minlength="10" maxlength="256" autocomplete="current-password" placeholder="حداقل ۱۰ نویسه"><button id="authSubmit" type="submit">ورود به پنل</button></div></form><div id="authError" class="error"></div><div class="notice" style="margin-top:16px">رمز عبورت را جای دیگری استفاده نکن. این حساب فعلاً برای پنل وب است؛ آمار تلگرام تا زمان اتصال حساب به شناسهٔ ربات، جداگانه نمایش داده می‌شود.</div></section>
<section id="app" class="hidden"><div class="row" style="justify-content:space-between"><div><h2 id="welcome">سلام!</h2><div class="muted" id="userEmail"></div></div><div class="row"><button class="secondary" id="reload">به‌روزرسانی</button><button class="secondary" id="logout">خروج</button></div></div>
<div class="grid"><div class="card metric"><div class="label">⏱ مجموع زمان مطالعه ثبت‌شده</div><div class="value" id="totalMinutes">۰</div><div class="muted">دقیقه</div></div><div class="card metric"><div class="label">🎯 هدف روزانه</div><div class="value" id="goalValue">۳۰</div><div class="muted">دقیقه در روز</div></div><div class="card metric"><div class="label">📆 امروز</div><div class="value" id="todayMinutes">۰</div><div class="muted">دقیقه ثبت‌شده</div></div></div>
<div class="card section"><h2>🎯 هدف مطالعه</h2><form id="goalForm" class="row"><input id="goal" type="number" min="5" max="600" required style="max-width:220px" aria-label="هدف روزانه به دقیقه"><button type="submit">ذخیره هدف</button></form><p class="muted">هدف روزانه را بین ۵ تا ۶۰۰ دقیقه تنظیم کن.</p></div>
<div class="card section"><h2>⏱ ثبت یک جلسه مطالعه</h2><form id="studyForm" class="row"><input id="minutes" type="number" min="1" max="600" required style="max-width:220px" placeholder="مدت به دقیقه"><input id="studyLabel" maxlength="80" placeholder="درس یا موضوع (اختیاری)" style="flex:1"><button type="submit">ثبت جلسه</button></form><p class="muted">این زمان را خودت ثبت می‌کنی؛ فعلاً با زمان‌های ثبت‌شده داخل ربات تلگرام یکی نیست.</p></div>
<div class="card section"><h2>📝 یادداشت‌های من</h2><form id="noteForm"><textarea id="note" rows="3" maxlength="1500" required placeholder="فرمول، نکته یا کاری که باید مرور کنی…"></textarea><div class="row" style="justify-content:flex-end;margin-top:9px"><button type="submit">ذخیره یادداشت</button></div></form><div id="notes"></div></div>
</section></main><div id="toast" class="toast hidden"></div><script>
const $=id=>document.getElementById(id);let mode="login";async function api(path,opts={}){const r=await fetch(path,{credentials:"same-origin",...opts,headers:{"Content-Type":"application/json",...(opts.headers||{})}});if(!r.ok)throw new Error(await r.text()||("HTTP "+r.status));return r.status===204?null:r.json()}function toast(t){$("toast").textContent=t;$("toast").classList.remove("hidden");setTimeout(()=>$("toast").classList.add("hidden"),3000)}function setMode(m){mode=m;$("authTitle").textContent=m==="login"?"خوش برگشتی 👋":"حساب درس‌یار بساز";$("authSubmit").textContent=m==="login"?"ورود به پنل":"ساخت حساب";$("name").classList.toggle("hidden",m==="login");$("tabLogin").className=m==="login"?"":"secondary";$("tabRegister").className=m==="register"?"":"secondary";$("password").autocomplete=m==="login"?"current-password":"new-password";$("authError").textContent=""}async function load(){const d=await api("/api/user/me");$("welcome").textContent="سلام "+(d.name||"دوست درس‌یار")+" 👋";$("userEmail").textContent=d.email;$("goal").value=d.goal;$("goalValue").textContent=Number(d.goal).toLocaleString("fa-IR");$("totalMinutes").textContent=Number(d.total_minutes).toLocaleString("fa-IR");$("todayMinutes").textContent=Number(d.today_minutes).toLocaleString("fa-IR");const notes=await api("/api/user/notes");$("notes").replaceChildren();for(const n of notes.items){const el=document.createElement("div");el.className="note";const p=document.createElement("div");p.textContent=n.text;const row=document.createElement("div");row.className="row";row.style.justifyContent="space-between";const time=document.createElement("small");time.textContent=n.created_at;const del=document.createElement("button");del.className="secondary";del.textContent="حذف";del.onclick=async()=>{try{await api("/api/user/notes/"+n.id,{method:"DELETE"});await load();toast("یادداشت حذف شد.")}catch{toast("حذف انجام نشد.")}};row.append(time,del);el.append(p,row);$("notes").append(el)}}async function showApp(){ $("auth").classList.add("hidden");$("app").classList.remove("hidden");await load()}$("tabLogin").onclick=()=>setMode("login");$("tabRegister").onclick=()=>setMode("register");$("authForm").onsubmit=async e=>{e.preventDefault();$("authSubmit").disabled=true;try{const payload={email:$("email").value.trim(),password:$("password").value};if(mode==="register")Object.assign(payload,{name:$("name").value.trim()});await api(mode==="login"?"/api/user/login":"/api/user/register",{method:"POST",body:JSON.stringify(payload)});$("password").value="";await showApp()}catch(err){$("authError").textContent=mode==="login"?"ورود انجام نشد؛ اطلاعات را بررسی کن.":"ثبت‌نام انجام نشد؛ شاید این ایمیل قبلاً ثبت شده یا اطلاعات معتبر نیست."}finally{$("authSubmit").disabled=false}};$("goalForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/user/goal",{method:"POST",body:JSON.stringify({goal:Number($("goal").value)})});await load();toast("هدف روزانه ذخیره شد.")}catch{toast("ذخیره هدف انجام نشد.")}};$("studyForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/user/study",{method:"POST",body:JSON.stringify({minutes:Number($("minutes").value),label:$("studyLabel").value.trim()})});$("minutes").value="";$("studyLabel").value="";await load();toast("جلسه مطالعه ثبت شد.")}catch{toast("ثبت جلسه ناموفق بود.")}};$("noteForm").onsubmit=async e=>{e.preventDefault();try{await api("/api/user/notes",{method:"POST",body:JSON.stringify({text:$("note").value.trim()})});$("note").value="";await load();toast("یادداشت ذخیره شد.")}catch{toast("ذخیره یادداشت ناموفق بود.")}};$("reload").onclick=()=>load().catch(()=>toast("دریافت اطلاعات ناموفق بود."));$("logout").onclick=async()=>{try{await api("/api/user/logout",{method:"POST"})}catch{}$("app").classList.add("hidden");$("auth").classList.remove("hidden");$("password").value=""};setMode("login");(async()=>{try{await showApp()}catch{}})();
</script></body></html>"""


def _secret() -> str:
    return os.getenv("WEB_SESSION_SECRET", "").strip()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return salt.hex() + ":" + digest.hex()


def _valid_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 240_000).hex()
        return hmac.compare_digest(expected, digest_hex)
    except (ValueError, TypeError):
        return False


def _cookie_value(email: str, expires: int) -> str:
    payload = f"{expires}:{email.casefold()}"
    sig = hmac.new(_secret().encode(), payload.encode(), "sha256").hexdigest()
    return payload + ":" + sig


def _user_email(request: web.Request) -> str | None:
    if not _secret():
        return None
    try:
        exp_s, email, sig = request.cookies.get(COOKIE, "").split(":", 2)
        exp = int(exp_s)
    except (ValueError, TypeError):
        return None
    payload = f"{exp}:{email}"
    expected = hmac.new(_secret().encode(), payload.encode(), "sha256").hexdigest()
    if exp < int(time.time()) or not hmac.compare_digest(sig, expected):
        return None
    return email


def _set_cookie(request: web.Request, response: web.Response, email: str):
    response.set_cookie(COOKIE, _cookie_value(email, int(time.time()) + 8 * 3600),
        httponly=True, secure=(request.headers.get("X-Forwarded-Proto", "").lower() == "https" or request.secure),
        samesite="Lax", max_age=8 * 3600, path="/")


def _require_user(request: web.Request) -> str:
    email = _user_email(request)
    if not email:
        raise web.HTTPUnauthorized(text="Please log in.")
    return email


async def _init(app: web.Application):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS portal_accounts(
            email TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL,
            daily_goal INTEGER NOT NULL DEFAULT 30, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS portal_study(
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, minutes INTEGER NOT NULL,
            label TEXT NOT NULL DEFAULT '', study_date TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS portal_notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, note TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_portal_study_email_date ON portal_study(email, study_date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_portal_notes_email ON portal_notes(email, id)")
        await db.commit()


async def register(request: web.Request):
    remote = request.remote or "unknown"
    now = time.time()
    attempts = [t for t in ATTEMPTS.get(remote, []) if now - t < 600]
    ATTEMPTS[remote] = attempts
    if len(attempts) >= 10:
        raise web.HTTPTooManyRequests(text="Too many attempts.")
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")
    email = str(data.get("email", "")).strip().casefold()[:254]
    password = str(data.get("password", ""))
    name = str(data.get("name", "")).strip()[:60]
    if "@" not in email or len(password) < 10 or len(password) > 256:
        attempts.append(now); ATTEMPTS[remote] = attempts
        raise web.HTTPBadRequest(text="Invalid account details.")
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO portal_accounts(email,name,password_hash) VALUES(?,?,?)",
                             (email, name, _hash_password(password)))
            await db.commit()
        except aiosqlite.IntegrityError:
            attempts.append(now); ATTEMPTS[remote] = attempts
            raise web.HTTPConflict(text="Account already exists.")
    ATTEMPTS.pop(remote, None)
    response = web.json_response({"ok": True})
    _set_cookie(request, response, email)
    return response


async def user_login(request: web.Request):
    remote = request.remote or "unknown"
    now = time.time()
    attempts = [t for t in ATTEMPTS.get(remote, []) if now - t < 600]
    ATTEMPTS[remote] = attempts
    if len(attempts) >= 10:
        raise web.HTTPTooManyRequests(text="Too many attempts.")
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")
    email = str(data.get("email", "")).strip().casefold()[:254]
    password = str(data.get("password", ""))[:256]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT password_hash FROM portal_accounts WHERE email=?", (email,)) as cur:
            row = await cur.fetchone()
    if not row or not _valid_password(password, row[0]):
        attempts.append(now); ATTEMPTS[remote] = attempts
        raise web.HTTPUnauthorized(text="Email or password incorrect.")
    ATTEMPTS.pop(remote, None)
    response = web.json_response({"ok": True})
    _set_cookie(request, response, email)
    return response


async def user_logout(request: web.Request):
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE, path="/", httponly=True, samesite="Lax")
    return response


async def me(request: web.Request):
    email = _require_user(request)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name,daily_goal FROM portal_accounts WHERE email=?", (email,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise web.HTTPUnauthorized(text="Account not found.")
        async with db.execute("SELECT COALESCE(SUM(minutes),0),COALESCE(SUM(CASE WHEN study_date=? THEN minutes ELSE 0 END),0) FROM portal_study WHERE email=?", (date.today().isoformat(), email)) as cur:
            total, today = await cur.fetchone()
    return web.json_response({"email": email, "name": row[0], "goal": row[1], "total_minutes": total, "today_minutes": today})


async def goal(request: web.Request):
    email = _require_user(request)
    try:
        data = await request.json()
        minutes = int(data.get("goal", 30))
    except (ValueError, TypeError, Exception):
        raise web.HTTPBadRequest(text="Invalid goal.")
    if not 5 <= minutes <= 600:
        raise web.HTTPBadRequest(text="Goal must be 5-600 minutes.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE portal_accounts SET daily_goal=? WHERE email=?", (minutes, email))
        await db.commit()
    return web.json_response({"ok": True, "goal": minutes})


async def study(request: web.Request):
    email = _require_user(request)
    try:
        data = await request.json()
        minutes = int(data.get("minutes", 0))
    except Exception:
        raise web.HTTPBadRequest(text="Invalid study session.")
    label = str(data.get("label", "")).strip()[:80]
    if not 1 <= minutes <= 600:
        raise web.HTTPBadRequest(text="Minutes must be 1-600.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO portal_study(email,minutes,label,study_date) VALUES(?,?,?,?)",
                         (email, minutes, label, date.today().isoformat()))
        await db.commit()
    return web.json_response({"ok": True})


async def notes(request: web.Request):
    email = _require_user(request)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,note,created_at FROM portal_notes WHERE email=? ORDER BY id DESC LIMIT 100", (email,)) as cur:
            rows = await cur.fetchall()
    return web.json_response({"items": [{"id": r[0], "text": r[1], "created_at": r[2]} for r in rows]})


async def add_note(request: web.Request):
    email = _require_user(request)
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON.")
    note = str(data.get("text", "")).strip()
    if not 1 <= len(note) <= 1500:
        raise web.HTTPBadRequest(text="Note must contain 1-1500 characters.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO portal_notes(email,note) VALUES(?,?)", (email, note))
        await db.commit()
    return web.json_response({"ok": True})


async def delete_note(request: web.Request):
    email = _require_user(request)
    try:
        note_id = int(request.match_info["note_id"])
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid note id.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM portal_notes WHERE id=? AND email=?", (note_id, email))
        await db.commit()
    return web.json_response({"ok": True})


def setup_user_portal(app: web.Application):
    app.on_startup.append(_init)
    app.router.add_get("/", portal_page)
    app.router.add_post("/api/user/register", register)
    app.router.add_post("/api/user/login", user_login)
    app.router.add_post("/api/user/logout", user_logout)
    app.router.add_get("/api/user/me", me)
    app.router.add_post("/api/user/goal", goal)
    app.router.add_post("/api/user/study", study)
    app.router.add_get("/api/user/notes", notes)
    app.router.add_post("/api/user/notes", add_note)
    app.router.add_delete("/api/user/notes/{note_id}", delete_note)


async def portal_page(_request: web.Request):
    return web.Response(text=HTML, content_type="text/html", charset="utf-8")
