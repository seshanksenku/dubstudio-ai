import hashlib
import hmac
import json
import os
import secrets
import shutil
import time
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.config import DATA, LANGUAGES
from app import store
from app.media import probe

PASSWORD = os.getenv('STUDIO_PASSWORD', '')
SECRET = os.getenv('SESSION_SECRET', '')
SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '100')) * 1024 * 1024
MAX_SECONDS = int(os.getenv('MAX_VIDEO_SECONDS', '60'))

@asynccontextmanager
async def lifespan(app):
    if len(PASSWORD) < 12 or len(SECRET) < 32:
        raise RuntimeError('Set STUDIO_PASSWORD (12+ characters) and SESSION_SECRET (32+ characters)')
    store.init()
    yield

app = FastAPI(title='DubStudio AI', lifespan=lifespan)

def signed(value):
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def authorized(request: Request):
    try:
        value, signature = request.cookies.get('studio_session', '').rsplit('.', 1)
        expiry, nonce = value.split(':', 1)
        if int(expiry) < time.time() or not hmac.compare_digest(signature, signed(value)):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(401, 'Sign in to your studio')

class Login(BaseModel):
    password: str

attempts = {}
@app.post('/api/login')
def login(body: Login, request: Request, response: Response):
    host = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    # Bounded process-local limit; use one API process behind Caddy.
    if len(attempts) > 1000:
        attempts.clear()
    previous = [t for t in attempts.get(host, []) if now-t < 60]
    if len(previous) >= 10:
        raise HTTPException(429, 'Try again in one minute')
    attempts[host] = previous + [now]
    if not hmac.compare_digest(body.password.encode(), PASSWORD.encode()):
        raise HTTPException(401, 'Incorrect studio password')
    value = f'{int(time.time()) + 86400}:{secrets.token_hex(16)}'
    response.set_cookie('studio_session', value+'.'+signed(value), httponly=True, secure=SECURE, samesite='strict', max_age=86400)
    return {'ok': True}

@app.post('/api/logout')
def logout(response: Response):
    response.delete_cookie('studio_session')
    return {'ok': True}

@app.get('/api/health')
def health():
    return {'ok': True}

@app.get('/api/config', dependencies=[Depends(authorized)])
def config():
    return {'languages': {key: value[0] for key, value in LANGUAGES.items()}, 'max_upload_mb': MAX_BYTES // 1024**2, 'max_video_seconds': MAX_SECONDS, 'worker_ready': store.worker_ready()}

def public(row):
    return {k: v for k, v in row.items() if k != 'payload'}

@app.get('/api/jobs', dependencies=[Depends(authorized)])
def jobs():
    return [public(row) for row in store.recent()]

@app.post('/api/jobs', status_code=202, dependencies=[Depends(authorized)])
def create(video: UploadFile = File(...), target: str = Form(...), source: str = Form('auto')):
    if target not in LANGUAGES or source not in {'auto', *LANGUAGES}:
        raise HTTPException(400, 'Unsupported language')
    if not store.worker_ready():
        raise HTTPException(503, 'GPU worker is offline or models are not ready. Check deployment logs.')
    if sum(row['status'] in ('running', 'queued') for row in store.recent()) >= 3:
        raise HTTPException(429, 'Studio queue is full. Wait for a job to finish.')
    suffix = Path(video.filename or '').suffix.lower()
    if suffix not in {'.mp4', '.mov', '.mkv', '.webm'}:
        raise HTTPException(400, 'Upload MP4, MOV, MKV or WebM')
    id = uuid4().hex
    folder = DATA / id
    folder.mkdir()
    path = folder / ('input'+suffix)
    try:
        total = 0
        with path.open('wb') as out:
            while chunk := video.file.read(1024*1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(413, 'Video exceeds upload size limit')
                out.write(chunk)
        try:
            duration, streams = probe(path)
        except Exception:
            raise HTTPException(400, 'Cannot read this video')
        if duration > MAX_SECONDS:
            raise HTTPException(400, f'Video must be {MAX_SECONDS} seconds or shorter')
        if not any(s['codec_type'] == 'video' for s in streams) or not any(s['codec_type'] == 'audio' for s in streams):
            raise HTTPException(400, 'Video needs a video track and spoken audio')
        store.add(id, {'input': path.name, 'source': source, 'target': target, 'duration': duration})
        return public(store.get(id))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        video.file.close()

@app.get('/api/jobs/{id}', dependencies=[Depends(authorized)])
def job(id: str):
    row = store.get(id)
    if not row:
        raise HTTPException(404, 'Job not found')
    result = public(row)
    transcript = DATA / id / 'transcript.json'
    if transcript.exists():
        result['transcript'] = json.loads(transcript.read_text())
    return result

@app.get('/api/jobs/{id}/download', dependencies=[Depends(authorized)])
def download(id: str):
    row = store.get(id)
    if not row or row['status'] != 'completed':
        raise HTTPException(404, 'Completed video unavailable')
    return FileResponse(DATA / id / 'dubbed.mp4', media_type='video/mp4', filename='DubStudio-dubbed.mp4')

@app.delete('/api/jobs/{id}', dependencies=[Depends(authorized)])
def delete(id: str):
    row = store.get(id)
    if not row:
        raise HTTPException(404, 'Job not found')
    if row['status'] in ('running', 'queued'):
        raise HTTPException(409, 'Wait until processing finishes')
    shutil.rmtree(DATA / row['id'], ignore_errors=True)
    store.remove(id)
    return {'ok': True}

app.mount('/', StaticFiles(directory=Path(__file__).resolve().parent.parent / 'web', html=True), name='web')
