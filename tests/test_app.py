import io
import os
import subprocess
import tempfile
from pathlib import Path

os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='dubstudio-test-')
os.environ['STUDIO_PASSWORD'] = 'private-test-password'
os.environ['SESSION_SECRET'] = 'testing-secret-with-more-than-32-characters'
os.environ['COOKIE_SECURE'] = 'false'

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import store
from app.media import tempo_chain

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def owner(client):
    assert client.post('/api/login', json={'password': 'private-test-password'}).status_code == 200
    return client

@pytest.fixture
def clip(tmp_path):
    path = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(path)], check=True)
    return path.read_bytes()

def test_private_job_routes(client):
    assert client.get('/api/jobs').status_code == 401
    assert client.get('/api/jobs/unknown/download').status_code == 401
    assert client.delete('/api/jobs/unknown').status_code == 401
    assert client.post('/api/login', json={'password':'incorrect'}).status_code == 401

def test_tampered_cookie(owner):
    value = owner.cookies['studio_session']
    owner.cookies.set('studio_session', value+'x')
    assert owner.get('/api/jobs').status_code == 401

def test_offline_worker(owner, clip, monkeypatch):
    monkeypatch.setattr(store, 'worker_ready', lambda: False)
    response = owner.post('/api/jobs', data={'target':'te'}, files={'video':('video.mp4',clip,'video/mp4')})
    assert response.status_code == 503

def test_job_lifecycle(owner, clip, monkeypatch):
    monkeypatch.setattr(store, 'worker_ready', lambda: True)
    response = owner.post('/api/jobs', data={'target':'te'}, files={'video':('../../strange name.mp4',clip,'video/mp4')})
    assert response.status_code == 202
    id = response.json()['id']
    assert 'payload' not in response.json()
    assert owner.get(f'/api/jobs/{id}/download').status_code == 404
    assert owner.delete(f'/api/jobs/{id}').status_code == 409
    row = store.claim()
    assert row['id'] == id
    assert store.claim() is None
    store.recover()
    assert owner.get(f'/api/jobs/{id}').json()['status'] == 'failed'
    assert owner.delete(f'/api/jobs/{id}').status_code == 200
    assert owner.get(f'/api/jobs/{id}').status_code == 404

def test_invalid_language_and_corrupt_video(owner, monkeypatch):
    monkeypatch.setattr(store, 'worker_ready', lambda: True)
    assert owner.post('/api/jobs', data={'target':'xx'}, files={'video':('x.mp4',b'invalid')}).status_code == 400
    assert owner.post('/api/jobs', data={'target':'te'}, files={'video':('x.mp4',b'invalid')}).status_code == 400

def test_upload_limit(owner, monkeypatch):
    import app.main as main
    monkeypatch.setattr(store, 'worker_ready', lambda: True)
    monkeypatch.setattr(main, 'MAX_BYTES', 10)
    assert owner.post('/api/jobs', data={'target':'en'}, files={'video':('x.mp4',b'x'*11)}).status_code == 413

def test_tempo_chain():
    for ratio in (.1, .5, 1, 2, 8):
        values = [float(x.split('=')[1]) for x in tempo_chain(ratio).split(',')]
        assert all(.5 <= v <= 2 for v in values)
        import math
        assert math.prod(values) == pytest.approx(ratio)
