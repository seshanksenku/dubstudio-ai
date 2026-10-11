import fcntl
import logging
import threading
import time
from app import store
from app.config import DATA
from app.pipeline import preflight, process

logging.basicConfig(level=logging.INFO)

def main():
    store.init()
    # Protect recovery/claim semantics against an accidental second worker.
    lock = (DATA / 'worker.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    preflight()
    store.recover()
    def beat():
        while True:
            store.heartbeat()
            time.sleep(5)
    threading.Thread(target=beat, daemon=True).start()
    while True:
        row = store.claim()
        if not row:
            time.sleep(2)
            continue
        try:
            process(row)
        except Exception as exc:
            logging.exception('Job %s failed', row['id'])
            store.update(row['id'], status='failed', stage='Processing failed', error=str(exc)[:500])

if __name__ == '__main__':
    main()
