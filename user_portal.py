"""Telegram-authenticated private DarsYar student portal."""
import hashlib, hmac, os, secrets, time
from aiohttp import web
import aiosqlite

DB_PATH=os.getenv("DB_PATH","./data/studybot.db")
COOKIE="darsyar_student"
HTML="""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل دانش‌آموزی درس‌یار</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f3ef;color:#262b32;font-family:Tahoma,Arial}main{max-width:920px;margin:auto;padding:28px 16px}.head,.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.muted{color:#68717d;font-size:13px;line-height:1.8}.card{background:#fff;border:1px solid #e1e0db;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 3px 12px #20202008}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.value{font-size:30px;color:#3e5a51;margin:12px 0}button,a{border:0;border-radius:9px;padding:12px 16px;background:#dce6df;color:#20372d;font-weight:bold;text-decoration:none;cursor:pointer}button.secondary{background:#eeefec;color:#343b42;border:1px solid #d7d9d5}input,textarea{width:100%;background:#fff;color:#262b32;border:1px solid #d4d7d2;border-radius:9px;padding:12px;margin:7px 0;font:inherit}.note{padding:12px;background:#f7f7f4;border:1px solid #e1e2dd;border-radius:9px;margin:9px 0;overflow-wrap:anywhere}.hidden{display:none}.notice{background:#f1f3ef;border:1px solid #dfe3dc;border-radius:9px;padding:12px;font-size:12px;line-height:1.8;color:#535f57}</style><main>
<header class="head"><div><h1>📘 پنل دانش‌آموزی درس‌یار</h1><p class="muted">فضای شخصی مطالعه، هدف‌ها و یادداشت‌های تو</p></div><a id="botlink" href="#">باز کردن ربات</a></header>
<section id="login" class="card"><h2>ورود امن با تلگرام</h2><p class="muted">برای تأیید هویت، به ربات درس‌یار برو و Start را بزن. رمز تلگرام از تو پرسیده نمی‌شود.</p><button id="begin">🔐 اتصال حساب تلگرام</button><p id="status" class="muted"></p><div class="notice">لینک ورود یک‌بارمصرف و کوتاه‌مدت است؛ آن را برای دیگران نفرست.</div></section>
<section id="panel" class="hidden"><div class="row"><div><h2 id="welcome">سلام!</h2><div id="identity" class="muted"></div></div><button id="logout" class="secondary">خروج</button></div>
<div class="grid"><div class="card"><div class="muted">⏱ مطالعه امروز</div><div class="value" id="today">۰</div><small>دقیقه ثبت‌شده</small></div><div class="card"><div class="muted">📚 کل زمان مطالعه</div><div class="value" id="total">۰</div><small>دقیقه</small></div><div class="card"><div class="muted">🧠 پاسخ‌های آزمون</div><div class="value" id="quiz">۰</div><small id="accuracy"></small></div></div>
<div class="card"><h2>🎯 هدف روزانه</h2><div class="row"><input id="goal" type="number" min="5" max="600" value="30" aria-label="هدف روزانه به دقیقه"><button id="saveGoal">ذخیره هدف</button></div></div>
<div class="card"><h2>📝 یادداشت‌های شخصی</h2><textarea id="note" rows="3" maxlength="1500" placeholder="نکته‌ای برای مرور..."></textarea><button id="addNote">ذخیره یادداشت</button><div id="notes"></div></div></section>
<div class="card"><h2>🤖 معلم هوشمند</h2><p class="muted">سؤال را بنویس؛ پاسخ با منابع مرتبط بررسی می‌شود، اگر جستجو در دسترس باشد.</p><textarea id="question" rows="3" maxlength="3000" placeholder="مثلاً: معادلهٔ خطی را با مثال توضیح بده"></textarea><button id="ask">پرسیدن از معلم</button><div id="answer" class="note" style="white-space:pre-wrap"></div></div>
<div class="card"><h2>🔎 جستجوی کمک‌درسی</h2><div class="row"><input id="searchQuery" maxlength="250" placeholder="موضوع یا سؤال درسی"><button id="searchStudy">جستجو</button></div><div id="searchResults"></div></div>
<div class="card"><h2>ابزارهای دیگر ربات</h2><p class="muted">برای آزمون، فلش‌کارت، برنامهٔ مطالعه، واژگان، فرمول‌ها و تایمر، ابزار موردنظر را باز کن.</p><div class="row" id="tools">
<a href="https://t.me/" id="botToolLink">باز کردن ربات</a>
<button class="secondary" data-cmd="/quiz">آزمون</button><button class="secondary" data-cmd="/daily">چالش روزانه</button><button class="secondary" data-cmd="/exam">آزمون ۵ سؤالی</button><button class="secondary" data-cmd="/flashcards">فلش‌کارت</button><button class="secondary" data-cmd="/review">مرور</button><button class="secondary" data-cmd="/plan">برنامه مطالعه</button><button class="secondary" data-cmd="/schedule 120">برنامه ۲ ساعته</button><button class="secondary" data-cmd="/goal 45">هدف ۴۵ دقیقه</button><button class="secondary" data-cmd="/done 25">ثبت ۲۵ دقیقه</button><button class="secondary" data-cmd="/formula">فرمول‌ها</button><button class="secondary" data-cmd="/vocab">واژگان</button><button class="secondary" data-cmd="/focus">تمرکز</button><button class="secondary" data-cmd="/timer 25">تایمر ۲۵ دقیقه</button><button class="secondary" data-cmd="/stoptimer">توقف تایمر</button><button class="secondary" data-cmd="/resources">کمک‌درسی</button><button class="secondary" data-cmd="/notes">یادداشت‌ها</button><button class="secondary" data-cmd="/privacy">حریم خصوصی</button><button class="secondary" data-cmd="/progress">پیشرفت</button><button class="secondary" data-cmd="/streak">زنجیره مطالعه</button><button class="secondary" data-cmd="/tip">نکته مطالعه</button><button class="secondary" data-cmd="/help">همه فرمان‌ها</button></div></div>
</main>
<script>const $=x=>document.getElementById(x);let botUrl='https://t.me/';async function api(p,o={}){let r=await fetch(p,{credentials:'same-origin',...o,headers:{'Content-Type':'application/json',...(o.headers||{})}});if(!r.ok)throw Error();return r.status===204?null:r.json()}
async function refresh(){let d=await api('/api/student/me');if(d.bot_url){botUrl=d.bot_url;$('botToolLink').href=botUrl;$('botlink').href=botUrl}$('login').classList.add('hidden');$('panel').classList.remove('hidden');$('welcome').textContent='سلام '+(d.first_name||'دوست درس‌یار')+' 👋';$('identity').textContent='حساب تلگرام متصل است'+(d.username?' • @'+d.username:'');$('today').textContent=d.today.toLocaleString('fa-IR');$('total').textContent=d.total.toLocaleString('fa-IR');$('quiz').textContent=d.answered.toLocaleString('fa-IR');$('accuracy').textContent=d.answered?'درستی پاسخ‌ها: '+d.accuracy+'٪':'هنوز آزمونی ثبت نشده';$('goal').value=d.goal;let n=await api('/api/student/notes');$('notes').replaceChildren(...n.items.map(x=>{let e=document.createElement('div');e.className='note';let t=document.createElement('div');t.textContent=x.text;let b=document.createElement('button');b.className='secondary';b.textContent='حذف';b.onclick=async()=>{await api('/api/student/notes/'+x.id,{method:'DELETE'});refresh()};e.append(t,document.createElement('br'),b);return e}))}
$('begin').onclick=async()=>{try{let d=await api('/api/student/login/start',{method:'POST',body:'{}'});$('botlink').href=d.url;botUrl=d.url.split('?')[0];$('botToolLink').href=botUrl;$('status').textContent='به ربات برو و Start را بزن؛ این صفحه را باز نگه دار.';let tries=0;async function poll(){if(tries++>90){$('status').textContent='مهلت ورود تمام شد؛ دوباره تلاش کن.';return}try{await api('/api/student/login/poll',{method:'POST',body:JSON.stringify({token:d.token})});await refresh()}catch{setTimeout(poll,2000)}}poll()}catch{$('status').textContent='شروع ورود ناموفق بود؛ دوباره تلاش کن.'}};
$('saveGoal').onclick=async()=>{try{await api('/api/student/goal',{method:'POST',body:JSON.stringify({goal:+$('goal').value})});alert('هدف ذخیره شد')}catch{alert('ذخیره هدف انجام نشد')}};
$('addNote').onclick=async()=>{try{await api('/api/student/notes',{method:'POST',body:JSON.stringify({text:$('note').value})});$('note').value='';refresh()}catch{alert('ذخیره یادداشت ناموفق بود')}};

$('logout').onclick=async()=>{await api('/api/student/logout',{method:'POST',body:'{}'});location.reload()};
$('ask').onclick=async()=>{let q=$('question').value.trim();if(!q)return;$('ask').disabled=true;$('answer').textContent='در حال بررسی سؤال…';try{let d=await api('/api/student/ask',{method:'POST',body:JSON.stringify({question:q})});$('answer').textContent=d.answer}catch{$('answer').textContent='پاسخ‌گویی فعلاً در دسترس نیست.'}finally{$('ask').disabled=false}};
$('searchStudy').onclick=async()=>{let q=$('searchQuery').value.trim();if(!q)return;$('searchStudy').disabled=true;$('searchResults').textContent='در حال جستجو…';try{let d=await api('/api/student/search',{method:'POST',body:JSON.stringify({query:q})});$('searchResults').replaceChildren(...d.items.map(x=>{let e=document.createElement('div');e.className='note';let t=document.createElement('strong');t.textContent=x.title;let p=document.createElement('p');p.textContent=x.snippet;let a=document.createElement('a');a.href=x.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='باز کردن منبع';e.append(t,p,a);return e}))}catch{$('searchResults').textContent='جستجو فعلاً ناموفق بود.'}finally{$('searchStudy').disabled=false}};
document.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=async()=>{try{await navigator.clipboard.writeText(b.dataset.cmd);b.textContent='کپی شد: '+b.dataset.cmd;setTimeout(()=>b.textContent=b.dataset.cmd,1600)}catch{prompt('این فرمان را در ربات بفرست:',b.dataset.cmd)}window.open(botUrl,'_blank','noopener')});
refresh().catch(()=>{});</script></html>"""

def _hash(token): return hashlib.sha256(token.encode()).hexdigest()
def _cookie(uid,exp):
 p=f"{exp}:{uid}";return p+":"+hmac.new(os.getenv("WEB_SESSION_SECRET","").encode(),p.encode(),"sha256").hexdigest()
def _uid(req):
 try: e,u,s=req.cookies.get(COOKIE,"").split(":",2);e=int(e);u=int(u)
 except Exception:return None
 p=f"{e}:{u}";sec=os.getenv("WEB_SESSION_SECRET","")
 if not sec or e<int(time.time()) or not hmac.compare_digest(s,hmac.new(sec.encode(),p.encode(),"sha256").hexdigest()):return None
 return u
def _require(req):
 u=_uid(req)
 if u is None:raise web.HTTPUnauthorized(text="Telegram login required")
 return u
async def init(app):
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("CREATE TABLE IF NOT EXISTS web_login_tickets(token_hash TEXT PRIMARY KEY,expires INTEGER NOT NULL,telegram_id INTEGER,first_name TEXT,username TEXT,used INTEGER NOT NULL DEFAULT 0)")
  await db.execute("CREATE TABLE IF NOT EXISTS web_student_notes(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
  await db.execute("CREATE INDEX IF NOT EXISTS idx_student_notes_owner ON web_student_notes(telegram_id,id)")
  await db.commit()
 app["bot_username"]=""
 if hasattr(app["bot"],"get_me"):
  try:
   me=await app["bot"].get_me();app["bot_username"]=me.username or ""
  except Exception:
   app["bot_username"]=""
async def page(_):return web.Response(text=HTML,content_type="text/html",charset="utf-8")
async def start_login(req):
 name=req.app.get("bot_username","")
 if not name:raise web.HTTPServiceUnavailable(text="Bot username unavailable")
 token=secrets.token_urlsafe(32);exp=int(time.time())+180
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("DELETE FROM web_login_tickets WHERE expires<? OR used=1",(int(time.time()),))
  await db.execute("INSERT INTO web_login_tickets(token_hash,expires) VALUES(?,?)",(_hash(token),exp));await db.commit()
 return web.json_response({"token":token,"url":f"https://t.me/{name}?start=web_{token}"})
async def poll_login(req):
 try:token=str((await req.json()).get("token",""))
 except Exception:raise web.HTTPBadRequest()
 async with aiosqlite.connect(DB_PATH) as db:
  async with db.execute("SELECT telegram_id,expires,used FROM web_login_tickets WHERE token_hash=?",(_hash(token),)) as c:r=await c.fetchone()
  if not r or not r[0] or r[1]<int(time.time()) or r[2]:raise web.HTTPUnauthorized()
  await db.execute("UPDATE web_login_tickets SET used=1 WHERE token_hash=? AND used=0",(_hash(token),));await db.commit()
 resp=web.json_response({"ok":True});resp.set_cookie(COOKIE,_cookie(r[0],int(time.time())+2592000),httponly=True,secure=(req.headers.get("X-Forwarded-Proto","").lower()=="https" or req.secure),samesite="Strict",max_age=2592000,path="/");return resp
async def complete_telegram_login(token,uid,first_name="",username=""):
 if not token or not uid:return False
 async with aiosqlite.connect(DB_PATH) as db:
  async with db.execute("SELECT expires,telegram_id FROM web_login_tickets WHERE token_hash=?",(_hash(token),)) as c:r=await c.fetchone()
  if not r or r[0]<int(time.time()) or r[1] is not None:return False
  await db.execute("UPDATE web_login_tickets SET telegram_id=?,first_name=?,username=? WHERE token_hash=? AND telegram_id IS NULL",(int(uid),str(first_name)[:100],str(username)[:100],_hash(token)));await db.commit()
 return True
async def me(req):
 uid=_require(req)
 async with aiosqlite.connect(DB_PATH) as db:
  async with db.execute("SELECT first_name,username FROM web_login_tickets WHERE telegram_id=? ORDER BY expires DESC LIMIT 1",(uid,)) as c:ident=await c.fetchone()
  async with db.execute("SELECT COALESCE(SUM(minutes),0),COALESCE(SUM(CASE WHEN study_date=date('now','localtime') THEN minutes ELSE 0 END),0) FROM study_days WHERE user_id=?",(uid,)) as c:st=await c.fetchone()
  async with db.execute("SELECT quiz_answered,quiz_correct FROM learning_stats WHERE user_id=?",(uid,)) as c:stats=await c.fetchone()
  async with db.execute("SELECT daily_goal FROM user_profiles WHERE user_id=?",(uid,)) as c:g=await c.fetchone()
 a,b=stats or (0,0)
 return web.json_response({"first_name":ident[0] if ident else "","username":ident[1] if ident else "","bot_url":("https://t.me/"+req.app.get("bot_username","")) if req.app.get("bot_username") else "","total":st[0] or 0,"today":st[1] or 0,"answered":a,"accuracy":round(b*100/a) if a else 0,"goal":g[0] if g else 30})

async def ask_student(req):
 uid=_require(req)
 try:question=str((await req.json()).get("question","")).strip()
 except Exception:raise web.HTTPBadRequest()
 if not 3<=len(question)<=3000:raise web.HTTPBadRequest()
 try:
  from bot import answer_question
  answer=await answer_question(question,user_id=uid)
 except Exception:
  return web.json_response({"answer":"پاسخ‌گویی فعلاً در دسترس نیست؛ از بخش جستجو استفاده کن."},status=200)
 return web.json_response({"answer":answer[:6500]})
async def search_student(req):
 uid=_require(req)
 try:query=str((await req.json()).get("query","")).strip()
 except Exception:raise web.HTTPBadRequest()
 if not 2<=len(query)<=250:raise web.HTTPBadRequest()
 try:
  from study_sources import search_study_sources
  items=await search_study_sources(query,limit=5)
 except Exception:
  items=[]
 return web.json_response({"items":[{"title":str(x.get("title",""))[:250],"snippet":str(x.get("snippet",""))[:700],"url":str(x.get("url",""))[:1000]} for x in items]})

async def set_goal(req):
 uid=_require(req)
 try:m=int((await req.json()).get("goal",30))
 except Exception:raise web.HTTPBadRequest()
 if not 5<=m<=600:raise web.HTTPBadRequest()
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("INSERT OR IGNORE INTO user_profiles(user_id,daily_goal) VALUES(?,?)",(uid,m));await db.execute("UPDATE user_profiles SET daily_goal=? WHERE user_id=?",(m,uid));await db.commit()
 return web.json_response({"ok":True})
async def notes(req):
 uid=_require(req)
 async with aiosqlite.connect(DB_PATH) as db:
  async with db.execute("SELECT id,note,created_at FROM web_student_notes WHERE telegram_id=? ORDER BY id DESC LIMIT 100",(uid,)) as c:rows=await c.fetchall()
 return web.json_response({"items":[{"id":x[0],"text":x[1],"created_at":x[2]} for x in rows]})
async def add_note(req):
 uid=_require(req)
 try:note=str((await req.json()).get("text","")).strip()
 except Exception:raise web.HTTPBadRequest()
 if not 1<=len(note)<=1500:raise web.HTTPBadRequest()
 async with aiosqlite.connect(DB_PATH) as db:await db.execute("INSERT INTO web_student_notes(telegram_id,note) VALUES(?,?)",(uid,note));await db.commit()
 return web.json_response({"ok":True})
async def delete_note(req):
 uid=_require(req)
 try:n=int(req.match_info["note_id"])
 except Exception:raise web.HTTPBadRequest()
 async with aiosqlite.connect(DB_PATH) as db:await db.execute("DELETE FROM web_student_notes WHERE id=? AND telegram_id=?",(n,uid));await db.commit()
 return web.json_response({"ok":True})
async def logout(_):
 r=web.json_response({"ok":True});r.del_cookie(COOKIE,path="/",httponly=True,samesite="Strict");return r
def setup_user_portal(app):
 global DB_PATH
 DB_PATH=app.get("db_path",DB_PATH)
 app.on_startup.append(init)
 app.router.add_get("/",page)
 app.router.add_post("/api/student/login/start",start_login)
 app.router.add_post("/api/student/login/poll",poll_login)
 app.router.add_get("/api/student/me",me)
 app.router.add_post("/api/student/ask",ask_student)
 app.router.add_post("/api/student/search",search_student)
 app.router.add_post("/api/student/goal",set_goal)
 app.router.add_get("/api/student/notes",notes)
 app.router.add_post("/api/student/notes",add_note)
 app.router.add_delete("/api/student/notes/{note_id}",delete_note)
 app.router.add_post("/api/student/logout",logout)
