import json
import sqlite3
import time
from contextlib import contextmanager
from app.config import DATA

@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'jobs.sqlite', timeout=30)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def init():
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, status TEXT, stage TEXT, progress INTEGER, payload TEXT, error TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS runtime (key TEXT PRIMARY KEY, value REAL)')

def heartbeat():
    with connection() as db:
        db.execute("INSERT OR REPLACE INTO runtime VALUES ('worker', ?)", (time.time(),))

def worker_ready():
    with connection() as db:
        row = db.execute("SELECT value FROM runtime WHERE key='worker'").fetchone()
    return bool(row and time.time() - row[0] < 30)

def add(id, payload):
    with connection() as db:
        db.execute("INSERT INTO jobs VALUES (?, ?, 'queued', 'Waiting for GPU', 0, ?, NULL)", (id, time.time(), json.dumps(payload)))

def update(id, status='running', stage='', progress=0, error=None):
    with connection() as db:
        db.execute('UPDATE jobs SET status=?, stage=?, progress=?, error=? WHERE id=?', (status, stage, progress, error, id))

def get(id):
    with connection() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (id,)).fetchone()
    return dict(row) if row else None

def recent():
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 50')]

def claim():
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE jobs SET status='running', stage='Starting' WHERE id=?", (row['id'],))
            return dict(row)

def recover():
    # Only ONE worker is supported. A process crash never leaves jobs falsely running.
    with connection() as db:
        db.execute("UPDATE jobs SET status='failed', stage='Interrupted', error='Worker restarted. Submit the video again.' WHERE status='running'")

def remove(id):
    with connection() as db:
        db.execute('DELETE FROM jobs WHERE id=?', (id,))
