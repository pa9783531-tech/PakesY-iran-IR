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
