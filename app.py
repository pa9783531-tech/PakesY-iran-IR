"""PakesY video studio with hosted signup, persistent media and owner-only features.

Automatic reactions and entertainment scores are simulated. The app can run
locally or as a single-instance service with a persistent storage volume.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

BASE = Path(__file__).resolve().parent
# The Railway volume location is injected automatically after attaching it.
# Keep BOTH the SQLite database and uploaded videos on that same volume.
if os.environ.get('RAILWAY_ENVIRONMENT') and not os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') and not os.environ.get('PAKESY_STORAGE_ROOT'):
    raise RuntimeError('Railway storage volume missing: attach a volume with mount path /data before deploying PakesY.')
STORAGE_ROOT = Path(os.environ.get('PAKESY_STORAGE_ROOT') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or str(BASE)).resolve()
DATA = STORAGE_ROOT / 'private_data'
MEDIA = STORAGE_ROOT / 'media'
ASSETS = BASE / 'assets'
DATA.mkdir(parents=True, exist_ok=True)
MEDIA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'pakesy.sqlite3'
SECRET_FILE = DATA / '.session_secret'
if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_hex(48), encoding='ascii')
    try: SECRET_FILE.chmod(0o600)
    except Exception: pass

SESSION_SECRET = os.getenv('PAKESY_SESSION_SECRET') or SECRET_FILE.read_text().strip()
OWNER_SETUP_CODE = os.getenv('PAKESY_OWNER_SETUP_CODE', '').strip()
COOKIE_SECURE = os.getenv('PAKESY_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes') or bool(os.getenv('RAILWAY_ENVIRONMENT'))
app = FastAPI(title='PakesY Online Creator Studio', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax', https_only=COOKIE_SECURE, max_age=60*60*24*14)
# The full index.html already bundles its CSS and JavaScript.
# The assets directory is optional (e.g. when only app.py/index.html were
# uploaded to GitHub). Never crash the whole web service if it is missing.
if ASSETS.is_dir():
    app.mount('/assets', StaticFiles(directory=str(ASSETS)), name='assets')
else:
    @app.get('/assets/cover.svg', include_in_schema=False)
    def fallback_cover():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360' viewBox='0 0 640 360'>"
               "<defs><linearGradient id='g' x2='1' y2='1'><stop stop-color='#20203c'/><stop offset='1' stop-color='#6b4baa'/></linearGradient></defs>"
               "<rect width='640' height='360' fill='url(#g)'/><text x='320' y='178' text-anchor='middle' fill='#c9fc50'"
               "font-family='Arial,sans-serif' font-size='56' font-weight='bold'>PakesY</text>"
               "<text x='320' y='220' text-anchor='middle' fill='white' font-family='Arial,sans-serif' font-size='24'>BedWars Video</text></svg>")
        return Response(content=svg, media_type='image/svg+xml')


MAX_FILE = 750 * 1024 * 1024
FEATURED_EMAIL = 'pa9783531@gmail.com'
BOT_POPULATION = 40_000
COMMENT_LANGS = ['en', 'ur', 'fa', 'ar', 'hi', 'tr', 'es', 'zh']
BOT_NAMES = ['Ayaan', 'Hassan', 'Zara', 'Hina', 'Danish', 'Hamza', 'Ali', 'Noor', 'Usman', 'Areeba', 'Sana', 'Rayan', 'Mina', 'Omar', 'Luna', 'Kaito', 'Leo', 'Dani', 'Sofia', 'Nima', 'Arman', 'Mehdi', 'Sara', 'Eren', 'Mia', 'Dev', 'Kian', 'Roya', 'Ibrahim', 'Sami']
BOT_TAGS = ['plays', 'pvper', 'rush', 'bedwars', 'clips', 'gg', 'combo', 'crafter', 'live', 'gaming', 'ninja', 'yt', 'pixel', 'blocks']

COMMENTS = {
 'en': ['That final clutch was unreal', 'Cleanest bridge I have seen today', 'The combo at the end was crazy', 'I watched this twice', 'The timing is actually perfect', 'This deserves way more love', 'The movement is so smooth', 'That defense was insane', 'Instant replay needed', 'The edits go hard', 'Next BedWars episode please', 'How did you survive that?', 'That last hit was legendary', 'Bro is playing on another level'],
 'ur': ['یہ کلچ کمال کا تھا', 'بھائی کیا زبردست گیم ہے', 'آخری فائٹ بہت مزے کی تھی', 'یہ ویڈیو دوبارہ دیکھنی پڑے گی', 'اتنا اچھا کمبو واہ', 'اگلی بیڈوارز ویڈیو جلدی لاؤ', 'موومنٹ بہت زبردست ہے', 'بہت ہی اچھی ایڈیٹنگ ہے'],
 'fa': ['این کلچ واقعاً خفن بود', 'آخرش رو چند بار دیدم', 'چه بریج زدنی عجب', 'ادیت خیلی تمیزه', 'کامبو آخرت عالی بود', 'منتظر ویدیوی بعدی بدوارزم', 'این حرکتت ترکوند', 'چه بازی باحالی'],
 'ar': ['لقطة النهاية أسطورية', 'مونتاج رهيب', 'اللعب سريع جدًا', 'أريد جزء ثاني', 'هذا الكومبو خرافي', 'شاهدت المقطع مرتين', 'حركة ذكية جدًا'],
 'hi': ['भाई आखिरी क्लच कमाल था', 'क्या जबरदस्त गेमप्ले है', 'यह एडिट बहुत बढ़िया है', 'अगला बेडवार्स वीडियो कब आएगा', 'कॉम्बो बहुत शानदार था'],
 'tr': ['Son hareket efsaneydi', 'Harika BedWars oynuyorsun', 'Bu kurgu çok iyi olmuş', 'Komboyu tekrar izledim', 'Yeni video gelsin'],
 'es': ['Ese clutch fue increíble', 'La edición está brutal', 'Qué buena partida de BedWars', 'Necesito otro video así', 'El combo final fue perfecto'],
 'zh': ['最后的操作太精彩了', '这个剪辑太酷了', '期待下一期起床战争', '这个连击太流畅了', '我又看了一遍'],
}
PREFIXES = ['', '', '', '🔥 ', 'GG! ', 'WOW! ', '💯 ', '⚡ ', '😮 ', '🏆 ']
SUFFIXES = ['', ' 🔥', ' 💯', ' 👏', ' 😍', ' GG', ' ⚡', ' ❤️', ' 👀', ' 🚀', '!!', ' ✨']
BOT_TITLES = ['BedWars | Perfect Final Clutch', 'The Rush That Changed Everything', 'One Heart Comeback', 'Fast Bridge Challenge', 'BedWars Combo Moments', 'Epic Last Second Save', 'Insane PvP Highlights', 'Best Bed Defense Moments']

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS owner (
              id INTEGER PRIMARY KEY CHECK(id=1), email TEXT UNIQUE NOT NULL,
              salt TEXT NOT NULL, password_hash TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
              email TEXT PRIMARY KEY, salt TEXT NOT NULL,
              password_hash TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS videos (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
              file_name TEXT NOT NULL, source_id TEXT,
              actor_id INTEGER NOT NULL DEFAULT 0, auto_edited INTEGER DEFAULT 0,
              created_at REAL NOT NULL, views INTEGER DEFAULT 0,
              likes INTEGER DEFAULT 0, target_comments INTEGER DEFAULT 500,
              target_likes INTEGER DEFAULT 2500, activity_start REAL NOT NULL,
              duration REAL DEFAULT 0, uploader_email TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL,
              actor_id INTEGER NOT NULL, body TEXT NOT NULL,
              created_at REAL NOT NULL, commenter_email TEXT NOT NULL DEFAULT '', 
              FOREIGN KEY(video_id) REFERENCES videos(id)
            );
            CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id, created_at DESC);
        ''')
        # Existing installs keep their videos; only add the missing attribution field.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(videos)')}
        if 'uploader_email' not in columns:
            db.execute("ALTER TABLE videos ADD COLUMN uploader_email TEXT NOT NULL DEFAULT ''")
        comment_columns = {row['name'] for row in db.execute('PRAGMA table_info(comments)')}
        if 'commenter_email' not in comment_columns:
            db.execute("ALTER TABLE comments ADD COLUMN commenter_email TEXT NOT NULL DEFAULT ''")
        old_owner = db.execute('SELECT * FROM owner WHERE id=1').fetchone()
        if old_owner:
            db.execute('''INSERT OR IGNORE INTO users(email,salt,password_hash,created_at)
                          VALUES(?,?,?,?)''',
                       (old_owner['email'], old_owner['salt'], old_owner['password_hash'], old_owner['created_at']))
            db.execute("UPDATE videos SET uploader_email=? WHERE actor_id=0 AND uploader_email=''", (old_owner['email'],))
            db.execute("UPDATE comments SET commenter_email=? WHERE actor_id=0 AND commenter_email=''", (old_owner['email'],))

init_db()

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 310000).hex()

def owner_exists():
    with connect() as db:
        return db.execute('SELECT 1 FROM owner WHERE id=1').fetchone() is not None

def owner_email():
    with connect() as db:
        row = db.execute('SELECT email FROM owner WHERE id=1').fetchone()
        return row['email'] if row else None

def current_email(request: Request) -> Optional[str]:
    email = request.session.get('account') or request.session.get('owner')
    if not isinstance(email, str):
        return None
    with connect() as db:
        found = db.execute('SELECT email FROM users WHERE email=?', (email,)).fetchone()
    return found['email'] if found else None

def authenticated(request: Request):
    return current_email(request) is not None

def require_auth(request: Request):
    email = current_email(request)
    if not email:
        raise HTTPException(status_code=401, detail='Sign in first')
    return email

class Credentials(BaseModel):
    email: str
    password: str
    setup_code: str = ''

class SimulateRequest(BaseModel):
    count: int = 500
    bot_videos: int = 2

_auth_events = {}
_auth_lock = Lock()
def rate_limit(request: Request, email: str, action: str):
    # Lightweight rate limit: use a dedicated gateway/WAF for heavy public traffic.
    now = time.monotonic()
    origin = request.client.host if request.client else 'unknown'
    key = (action, origin, email.lower().strip()[:254])
    with _auth_lock:
        events = [t for t in _auth_events.get(key, []) if now-t < 600]
        if len(events) >= 15:
            raise HTTPException(429, 'Too many attempts; please try again later')
        events.append(now)
        _auth_events[key] = events
        if len(_auth_events) > 5000:
            for k, vals in list(_auth_events.items()):
                if not vals or now-vals[-1] > 600:
                    _auth_events.pop(k, None)

def valid_credentials(data: Credentials):
    email = data.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise HTTPException(400, 'Enter a valid email')
    if len(data.password) < 8 or len(data.password) > 256:
        raise HTTPException(400, 'Password must be between 8 and 256 characters')
    return email

@app.get('/healthz')
def healthz():
    return {'ok': True}

@app.get('/')
def index():
    return FileResponse(BASE / 'index.html', media_type='text/html')

@app.get('/api/status')
def status(request: Request):
    email = current_email(request)
    with connect() as db:
        has_accounts = db.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None
    return {'registered': has_accounts, 'authenticated': bool(email),
            'email': email, 'featured_account': email == FEATURED_EMAIL}

@app.post('/api/register')
def register(data: Credentials, request: Request):
    email = valid_credentials(data)
    rate_limit(request, email, 'register')
    salt = secrets.token_hex(24)
    with connect() as db:
        primary = db.execute('SELECT email FROM owner WHERE id=1').fetchone()
        if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
            raise HTTPException(409, 'Email already registered')
        if email == FEATURED_EMAIL:
            # Do NOT allow someone to steal the privileged account simply by
            # entering its publicly visible email before the real owner does.
            if primary and primary['email'] != FEATURED_EMAIL:
                raise HTTPException(409, 'Primary account needs administrator migration')
            if not OWNER_SETUP_CODE:
                raise HTTPException(503, 'Owner sign-up must be enabled with PAKESY_OWNER_SETUP_CODE on the host')
            if not hmac.compare_digest(data.setup_code, OWNER_SETUP_CODE):
                raise HTTPException(403, 'Incorrect owner setup code')
        pw_hash=hash_password(data.password,salt)
        now=time.time()
        if email == FEATURED_EMAIL and not primary:
            db.execute('INSERT INTO owner(id,email,salt,password_hash,created_at) VALUES(1,?,?,?,?)',
                       (email,salt,pw_hash,now))
        db.execute('INSERT INTO users(email,salt,password_hash,created_at) VALUES(?,?,?,?)',
                   (email,salt,pw_hash,now))
    request.session.clear()
    request.session['account'] = email
    # Registration creates no posts or reactions.
    return {'ok': True, 'email': email}

@app.post('/api/login')
def login(data: Credentials, request: Request):
    email = data.email.strip().lower()
    rate_limit(request, email, 'login')
    with connect() as db:
        row = db.execute('SELECT email,salt,password_hash FROM users WHERE email=?', (email,)).fetchone()
    salt = row['salt'] if row else '0'*48
    result = hash_password(data.password,salt)
    if not row or not hmac.compare_digest(row['password_hash'], result):
        raise HTTPException(401, 'Wrong email or password')
    request.session.clear()
    request.session['account'] = row['email']
    return {'ok': True, 'email': row['email']}

@app.post('/api/logout')
def logout(request: Request):
    request.session.clear()
    return {'ok': True}

def account_persona(email: str):
    if email == FEATURED_EMAIL:
        return persona(0)
    handle = email.split('@')[0][:22] if email else 'Creator'
    return {'name': handle or 'Creator', 'initial': (handle or 'C')[0].upper(),
            'color': '#86c2ff', 'owner': False}

def persona(actor_id: int):
    if actor_id == 0:
        return {'name': 'PakesY Creator', 'initial': 'P', 'color': '#c7ff42', 'owner': True}
    rng = random.Random(actor_id * 104729)
    name = f'{rng.choice(BOT_NAMES)}_{rng.choice(BOT_TAGS)}{rng.randint(10,999)}'
    colors = ['#9d88ff','#ff9a73','#81e3cf','#a9b7ff','#fbc56d','#ff7ea8','#8ee6ff','#deee88']
    return {'name': name, 'initial': name[0].upper(), 'color': rng.choice(colors), 'owner': False}

def decorate(row, viewer_email: str):
    v = dict(row)
    v['author'] = account_persona(v['uploader_email']) if v['actor_id'] == 0 else {'name': 'PakesY Highlights', 'initial': 'P', 'color': '#ab8aff', 'owner': False}
    v['likes'] = int(v['likes'])
    v['is_owner'] = v['actor_id'] == 0 and v.get('uploader_email') == viewer_email
    v['is_featured'] = v['actor_id'] == 0 and v.get('uploader_email') == FEATURED_EMAIL
    v['comments'] = int(v.get('comments',0))
    v['url'] = '/api/media/' + v['file_name']
    poster = v['file_name'].rsplit('.',1)[0]+'.jpg'
    v['poster_url'] = '/api/poster/'+poster if (MEDIA/poster).is_file() else '/assets/cover.svg'
    return v

# Activity is generated as requests arrive; no 40,000 OS workers are created.
def simulate_engagement(db, video_id: str, how_many: int, *, span_hours: float=0):
    row = db.execute('SELECT * FROM videos WHERE id=?',(video_id,)).fetchone()
    if not row or how_many <= 0:
        return 0
    base_count = db.execute('SELECT COUNT(*) n FROM comments WHERE video_id=?',(video_id,)).fetchone()['n']
    already_used = set(r['actor_id'] for r in db.execute('SELECT actor_id FROM comments WHERE video_id=? AND actor_id>0',(video_id,)).fetchall())
    existing_bodies = set(r['body'] for r in db.execute('SELECT body FROM comments WHERE video_id=?',(video_id,)).fetchall())
    rng = random.Random(f'{video_id}-{base_count}-pakesy')
    pool = list(range(1, BOT_POPULATION+1))
    rng.shuffle(pool)
    users = (i for i in pool if i not in already_used)
    insert = []
    for i in range(min(how_many, BOT_POPULATION-len(already_used))):
        try: actor_id = next(users)
        except StopIteration: break
        lang = COMMENT_LANGS[(i+base_count+actor_id)%len(COMMENT_LANGS)]
        parts = COMMENTS[lang]
        for attempt in range(100):
            core = rng.choice(parts)
            body = rng.choice(PREFIXES) + core + rng.choice(SUFFIXES)
            if rng.random() < .17:
                body += f' #{rng.choice(["BedWars","GG","PvP","Minecraft","PakesY", "clutch"])}'
            if body not in existing_bodies:
                break
        else:
            body += f' #{actor_id}'
        existing_bodies.add(body)
        created = time.time()-rng.uniform(0,span_hours*3600) if span_hours else time.time()-rng.random()*50
        insert.append((video_id,actor_id,body,created))
    db.executemany('INSERT INTO comments(video_id,actor_id,body,created_at) VALUES(?,?,?,?)', insert)
    db.execute('UPDATE videos SET likes=MIN(40000,likes+?),views=views+? WHERE id=?', (len(insert)*rng.randint(3,9),len(insert)*rng.randint(8,22),video_id))
    return len(insert)

def activity_tick(db):
    now=time.time()
    # Engagement automation belongs ONLY to original uploads by the featured email.
    rows=db.execute('SELECT id,actor_id,target_comments,target_likes,activity_start,likes FROM videos WHERE actor_id=0 AND uploader_email=?',(FEATURED_EMAIL,)).fetchall()
    for row in rows:
        elapsed=max(0,now-row['activity_start'])
        progress=min(1.0,elapsed/(48*3600))
        count=db.execute('SELECT COUNT(*) n FROM comments WHERE video_id=?',(row['id'],)).fetchone()['n']
        target=min(row['target_comments'], 18+int(progress*max(0,row['target_comments']-18)))
        if count < target:
            simulate_engagement(db,row['id'],min(target-count,1000))
        # Likes are simulated and can grow independently of comment arrival.
        likes_target=int(110+progress*max(0,row['target_likes']-110))
        if row['likes']<likes_target:
            db.execute('UPDATE videos SET likes=? WHERE id=?', (likes_target,row['id']))
        if row['actor_id']==0:
            # After 48h, up to four virtual remix posts reference owner footage.
            remix_target=sum(progress>=mark for mark in (0.12,0.37,0.62,0.87))
            existing=db.execute('SELECT COUNT(*) n FROM videos WHERE source_id=?',(row['id'],)).fetchone()['n']
            if remix_target>existing:
                src=db.execute('SELECT file_name,duration FROM videos WHERE id=?',(row['id'],)).fetchone()
                for i in range(existing,remix_target):
                    rng=random.Random(f'{row["id"]}-remix-{i}')
                    remix_id=uuid.uuid4().hex[:16]
                    db.execute('''INSERT INTO videos(id,title,description,file_name,source_id,actor_id,auto_edited,created_at,views,likes,target_comments,target_likes,activity_start,duration)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (remix_id,rng.choice(BOT_TITLES),'Highlight cut of the original video',src['file_name'],row['id'],rng.randrange(1,BOT_POPULATION+1),0,now,0,0,0,0,now,src['duration']))

def background_tick_once():
    with connect() as db:
        activity_tick(db)

async def background_activity():
    # Continues to add reactions while the local server runs, even if the
    # browser is closed. On reopening, feed fetch catches up from upload time.
    while True:
        try:
            await asyncio.to_thread(background_tick_once)
        except Exception as exc:
            print(f'PakesY activity worker: {exc}')
        await asyncio.sleep(20)

@app.on_event('startup')
async def start_activity_worker():
    app.state.activity_worker = asyncio.create_task(background_activity())

@app.on_event('shutdown')
async def stop_activity_worker():
    task = getattr(app.state, 'activity_worker', None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

@app.get('/api/feed')
def feed(request: Request, q: str='', tab: str='for-you'):
    viewer = require_auth(request)
    with connect() as db:
        activity_tick(db)
        # Exclude sample/standalone persona uploads from the visible feed.
        where="WHERE (v.actor_id=0 OR v.source_id IS NOT NULL)"
        params=[]
        if q:
            where+=' AND v.title LIKE ?'
            params.append(f'%{q}%')
        rows=db.execute(f'''SELECT v.*, (SELECT COUNT(*) FROM comments c WHERE c.video_id=v.id) comments
            FROM videos v {where} ORDER BY (v.actor_id=0 AND v.uploader_email=?) DESC, v.created_at DESC LIMIT 100''',(*params,FEATURED_EMAIL)).fetchall()
        items=[decorate(r, viewer) for r in rows]
        if tab=='mine': items=[v for v in items if v['is_owner']]
        if tab=='trending': items=sorted(items,key=lambda v:(not v['is_featured'],-v['likes'], -v['created_at']))
        comments_total=db.execute('SELECT COUNT(*) n FROM comments WHERE video_id IN (SELECT id FROM videos WHERE actor_id=0 AND uploader_email=?)',(viewer,)).fetchone()['n']
        likes_total=db.execute('SELECT COALESCE(SUM(likes),0) n FROM videos WHERE actor_id=0 AND uploader_email=?',(viewer,)).fetchone()['n']
        views_total=db.execute('SELECT COALESCE(SUM(views),0) n FROM videos WHERE actor_id=0 AND uploader_email=?',(viewer,)).fetchone()['n']
        video_total=db.execute('SELECT COUNT(*) n FROM videos WHERE actor_id=0 AND uploader_email=?',(viewer,)).fetchone()['n']
    # Internal entertainment-only score, not a payment or withdrawable balance.
    demo_earnings=(4_000_000+views_total*7) if video_total and viewer == FEATURED_EMAIL else 0
    return {'videos':items,'stats':{'videos':video_total,'comments':comments_total,'likes':likes_total,'views':views_total,'demo_earnings':demo_earnings}}

@app.get('/api/videos/{video_id}/comments')
def comments(video_id: str, request: Request, limit: int=60):
    require_auth(request)
    with connect() as db:
        if not db.execute('SELECT 1 FROM videos WHERE id=?',(video_id,)).fetchone():
            raise HTTPException(404, 'Video not found')
        rows=db.execute('SELECT * FROM comments WHERE video_id=? ORDER BY created_at DESC LIMIT ?', (video_id,max(1,min(limit,500)))).fetchall()
    return {'comments':[{'id':r['id'],'body':r['body'],'created_at':r['created_at'],
            'author':persona(r['actor_id']) if r['actor_id'] != 0 else account_persona(r['commenter_email'] or owner_email() or '')} for r in rows]}

@app.post('/api/videos/{video_id}/comment')
async def add_comment(video_id: str, request: Request):
    viewer = require_auth(request)
    data=await request.json()
    body=str(data.get('body','')).strip()[:500]
    if not body: raise HTTPException(400,'Empty comment')
    with connect() as db:
        if not db.execute('SELECT 1 FROM videos WHERE id=?',(video_id,)).fetchone():
            raise HTTPException(404,'Video not found')
        db.execute('INSERT INTO comments(video_id,actor_id,body,created_at,commenter_email) VALUES(?,?,?,?,?)', (video_id,0,body,time.time(),viewer))
    return {'ok':True}

@app.get('/api/media/{file_name}')
def media(file_name: str, request: Request):
    require_auth(request)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+',file_name):
        raise HTTPException(404,'No file')
    with connect() as db:
        found=db.execute('SELECT 1 FROM videos WHERE file_name=? LIMIT 1',(file_name,)).fetchone()
    path=MEDIA/file_name
    if not found or not path.is_file(): raise HTTPException(404,'No file')
    return FileResponse(path,media_type='video/mp4',filename=file_name,content_disposition_type='inline')

@app.get('/api/poster/{file_name}')
def poster(file_name: str,request: Request):
    require_auth(request)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.jpg',file_name):
        raise HTTPException(404,'No poster')
    matching_movie=file_name[:-4]+'.mp4'
    with connect() as db:
        found=db.execute('SELECT 1 FROM videos WHERE file_name=? LIMIT 1',(matching_movie,)).fetchone()
    path=MEDIA/file_name
    if not found or not path.is_file():raise HTTPException(404,'No poster')
    return FileResponse(path,media_type='image/jpeg')

def make_poster(video: Path, seconds: float):
    poster=video.with_suffix('.jpg')
    try:
        subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss',str(max(0,min(seconds/2,3))),'-i',str(video),'-frames:v','1','-vf','scale=640:-2',str(poster)],check=True,timeout=30,capture_output=True)
    except Exception:
        poster.unlink(missing_ok=True)

def probe_video(path: Path):
    if not shutil.which('ffprobe'):
        raise HTTPException(500,'ffprobe not installed')
    cmd=['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type', '-of','json',str(path)]
    try:
        p=subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=35)
        data=json.loads(p.stdout)
        duration=float(data.get('format',{}).get('duration',0))
        if duration<=0: raise ValueError('not a video')
        audio=any(s.get('codec_type')=='audio' for s in data.get('streams',[]))
        picture=any(s.get('codec_type')=='video' for s in data.get('streams',[]))
        if not picture or duration>14400: raise ValueError('no video or duration too long')
        return duration,audio
    except (Exception) as exc:
        raise HTTPException(400,f'Invalid or unsupported video: {str(exc)[:100]}') from exc

# Edits cut to a 35-second BedWars-style montage by selecting 5 moments across
# the source, adjust color & sharpness, resize for web, and normalize sound.
# It does NOT claim AI understanding of gameplay/highlights.
def auto_edit_video(inp: Path, out: Path, duration: float, has_audio: bool):
    if not shutil.which('ffmpeg'): raise HTTPException(500,'ffmpeg not installed')
    visual='scale=-2:720:flags=lanczos,fps=30,eq=contrast=1.06:saturation=1.13,unsharp=3:3:0.65'
    if duration<=35:
        args=['-i',str(inp),'-vf',visual]
    else:
        segments=5
        clip=6.0
        starts=[round(i*(duration-clip)/(segments-1),2) for i in range(segments)]
        # Multiple seeks reuse input and create a true multi-cut montage.
        args=[]
        for start in starts: args+=['-ss',str(start),'-t',str(clip),'-i',str(inp)]
        vfilters=';'.join(f'[{i}:v]{visual},setpts=PTS-STARTPTS[v{i}]' for i in range(segments))
        if has_audio:
            afilters=';'.join(f'[{i}:a]aresample=async=1,asetpts=PTS-STARTPTS[a{i}]' for i in range(segments))
            pairs=''.join(f'[v{i}][a{i}]' for i in range(segments))
            filt=vfilters+';'+afilters+';'+pairs+f'concat=n={segments}:v=1:a=1[outv][outa]'
            args+=['-filter_complex',filt,'-map','[outv]','-map','[outa]']
        else:
            pairs=''.join(f'[v{i}]' for i in range(segments))
            filt=vfilters+';'+pairs+f'concat=n={segments}:v=1:a=0[outv]'
            args+=['-filter_complex',filt,'-map','[outv]']
    if duration<=35 and has_audio:
        args+=['-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','128k']
    elif duration>35 and has_audio:
        args+=['-c:a','aac','-b:a','128k']
    else:
        args+=['-an']
    cmd=['ffmpeg','-y','-hide_banner','-loglevel','error']+args+['-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',str(out)]
    try: subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=300)
    except subprocess.TimeoutExpired as exc: raise HTTPException(500,'Editing timed out') from exc
    except subprocess.CalledProcessError as exc: raise HTTPException(500, 'Video editor failed: '+exc.stderr[-400:]) from exc

@app.post('/api/upload')
async def upload(request: Request, file: UploadFile=File(...), title: str=Form(''), description: str=Form(''), auto_edit: str=Form('true')):
    uploader = require_auth(request)
    title=title.strip()[:140]
    if not title: raise HTTPException(400,'Give this video a title')
    filename=(file.filename or '').lower()
    if not filename.endswith(('.mp4','.mov','.webm','.mkv','.m4v')):
        raise HTTPException(400,'Please upload MP4, MOV, WEBM, MKV, or M4V')
    temp=MEDIA/(uuid.uuid4().hex+'.upload')
    final=MEDIA/(uuid.uuid4().hex+'.mp4')
    size=0
    try:
        with temp.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_FILE: raise HTTPException(413,'Video limit is 750MB')
                out.write(chunk)
        duration,has_audio=await asyncio.to_thread(probe_video,temp)
        if auto_edit.lower() in ['true','1','yes','on']:
            await asyncio.to_thread(auto_edit_video,temp,final,duration,has_audio)
            out_duration=min(35,duration) if duration<=35 else 30
            edited=1
        else:
            # Re-encode to MP4 so browser playback works across input formats.
            if not shutil.which('ffmpeg'): raise HTTPException(500,'ffmpeg missing')
            cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(temp),'-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(final)]
            await asyncio.to_thread(subprocess.run,cmd,check=True,capture_output=True,timeout=300)
            out_duration=duration;edited=0
        await asyncio.to_thread(make_poster,final,out_duration)
        vid=uuid.uuid4().hex[:16]
        now=time.time()
        is_featured = uploader == FEATURED_EMAIL
        with connect() as db:
            db.execute('''INSERT INTO videos(id,title,description,file_name,actor_id,auto_edited,created_at,views,likes,target_comments,target_likes,activity_start,duration,uploader_email)
                          VALUES(?,?,?,?,0,?,?,?,?,?,?,?,?,?)''',
                        (vid,title,description.strip()[:1000],final.name,edited,now,0,0,500 if is_featured else 0,2800 if is_featured else 0,now,out_duration,uploader or ''))
            # The first reactions are triggered by a finished upload, never login.
            if is_featured:
                simulate_engagement(db,vid,18)
        return {'ok':True,'video_id':vid,'edited':bool(edited)}
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500,'FFmpeg conversion failed') from exc
    finally:
        await file.close()
        temp.unlink(missing_ok=True)
        if not final.exists() or final.stat().st_size==0: final.unlink(missing_ok=True)

@app.post('/api/videos/{video_id}/simulate')
def simulate(video_id: str, data: SimulateRequest, request: Request):
    viewer = require_auth(request)
    if viewer != FEATURED_EMAIL:
        raise HTTPException(403, 'Only the primary creator can use this action')
    if data.count<0 or data.count>2000 or data.bot_videos<0 or data.bot_videos>6:
        raise HTTPException(400,'Use up to 2,000 comments and 6 remixes')
    now=time.time()
    with connect() as db:
        original=db.execute('SELECT * FROM videos WHERE id=?',(video_id,)).fetchone()
        if not original: raise HTTPException(404,'Video not found')
        if original['actor_id'] != 0 or original['uploader_email'] != FEATURED_EMAIL:
            raise HTTPException(403,'Only videos uploaded by the featured account can receive activity')
        current=db.execute('SELECT COUNT(*) n FROM comments WHERE video_id=?',(video_id,)).fetchone()['n']
        added=simulate_engagement(db,video_id,max(0,data.count-current),span_hours=48)
        if data.count>=500:
            db.execute('UPDATE videos SET likes=MAX(likes,4500),views=MAX(views,60000),target_comments=MAX(target_comments,?) WHERE id=?',(data.count,video_id))
        created=[]
        # Private remixes point at original footage that the owner uploaded.
        # No third-party content is scraped or downloaded.
        for i in range(data.bot_videos):
            rng=random.Random(f'{video_id}-{now}-{i}')
            bot=rng.randint(1,BOT_POPULATION)
            new_id=uuid.uuid4().hex[:16]
            db.execute('''INSERT INTO videos(id,title,description,file_name,source_id,actor_id,auto_edited,created_at,views,likes,target_comments,target_likes,activity_start,duration)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (new_id,rng.choice(BOT_TITLES),'Highlight cut of the original video',original['file_name'],video_id,bot,0,now-i*60,0,0,0,0,now,original['duration']))
            created.append(new_id)
    return {'ok':True,'added_comments':added,'created_videos':len(created)}

@app.delete('/api/videos/{video_id}')
def delete_video(video_id: str, request: Request):
    viewer = require_auth(request)
    with connect() as db:
        video=db.execute('SELECT * FROM videos WHERE id=?',(video_id,)).fetchone()
        if not video or video['actor_id']!=0 or video['uploader_email']!=viewer:
            raise HTTPException(404,'Your video not found')
        dependents=[r['id'] for r in db.execute('SELECT id FROM videos WHERE source_id=?',(video_id,)).fetchall()]
        ids=[video_id]+dependents
        db.executemany('DELETE FROM comments WHERE video_id=?',[(i,) for i in ids])
        db.executemany('DELETE FROM videos WHERE id=?',[(i,) for i in ids])
        remaining=db.execute('SELECT 1 FROM videos WHERE file_name=? LIMIT 1',(video['file_name'],)).fetchone()
    if not remaining:
        (MEDIA/video['file_name']).unlink(missing_ok=True)
        (MEDIA/video['file_name']).with_suffix('.jpg').unlink(missing_ok=True)
    return {'ok':True}
