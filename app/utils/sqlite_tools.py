"""SQLite helpers for safe snapshots and in-place restores of the live database.

The live database runs in WAL mode with mmap enabled and is open in the web
process (and Celery). Copying or overwriting the file directly leaves a stale
-wal/-shm behind and pulls the file out from under open connections, so
snapshots go through VACUUM INTO and restores through SQLite's backup API.
"""
import os
import shutil
import sqlite3
import threading

REQUIRED_TABLES = frozenset({'users', 'system_settings', 'tasks'})

# Only one export/import/restore at a time.
_maintenance_lock = threading.Lock()


def try_lock() -> bool:
    return _maintenance_lock.acquire(blocking=False)


def unlock() -> None:
    try:
        _maintenance_lock.release()
    except RuntimeError:
        pass


def run_blocking(fn, *args, **kwargs):
    """Run a blocking call in a native thread so the gevent hub keeps serving requests."""
    try:
        from gevent import get_hub
        from gevent.monkey import is_module_patched
        if is_module_patched('socket'):
            return get_hub().threadpool.spawn(fn, *args, **kwargs).get()
    except ImportError:
        pass
    return fn(*args, **kwargs)


def remove_db_files(path: str) -> None:
    """Delete a database file together with its -wal/-shm/-journal companions."""
    for suffix in ('', '-wal', '-shm', '-journal'):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def has_free_space(directory: str, needed_bytes: int) -> bool:
    try:
        return shutil.disk_usage(directory).free > needed_bytes
    except OSError:
        return True


def stream_and_delete(path: str, chunk_size: int = 1024 * 1024):
    """Yield a file in chunks and delete it afterwards, even if the client disconnects."""
    try:
        with open(path, 'rb') as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        remove_db_files(path)


def snapshot_db(src_path: str, dest_path: str) -> None:
    """Write a consistent, self-contained copy of an in-use database."""
    remove_db_files(dest_path)
    src = sqlite3.connect(src_path, timeout=60)
    try:
        src.execute('VACUUM INTO ?', (dest_path,))
    finally:
        src.close()
    # Make the copy independent of -wal/-shm files.
    dst = sqlite3.connect(dest_path)
    try:
        dst.execute('PRAGMA journal_mode=DELETE')
    finally:
        dst.close()


def validate_db_file(path: str) -> tuple[bool, str]:
    """Check that *path* is an intact BPM-Tutor database."""
    try:
        with open(path, 'rb') as fh:
            if not fh.read(16).startswith(b'SQLite format 3\x00'):
                return False, 'Invalid file — not a valid SQLite database.'
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute('PRAGMA integrity_check(10)').fetchall()
            if rows != [('ok',)]:
                problems = '; '.join(str(r[0]) for r in rows[:5])
                return False, f'Database file is corrupt (integrity_check failed): {problems}'
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except (sqlite3.DatabaseError, OSError) as exc:
        return False, f'Database file is corrupt: {exc}'
    finally:
        # Opening a WAL-flagged file may have created companion files.
        for suffix in ('-wal', '-shm', '-journal'):
            try:
                os.remove(path + suffix)
            except OSError:
                pass
    missing = REQUIRED_TABLES - tables
    if missing:
        return False, f'Not a BPM-Tutor database (missing tables: {", ".join(sorted(missing))}).'
    return True, ''


def restore_into_live(live_path: str, source_path: str) -> None:
    """Overwrite the live database with *source_path* using SQLite's backup API.

    The copy runs as one write transaction, so a failure leaves the live
    database untouched and other connections never see a half-written file.
    If the live file is unreadable (corrupt) or cannot take the pages (WAL
    page-size mismatch), the file is replaced instead.
    """
    src = sqlite3.connect(source_path)
    try:
        dst = sqlite3.connect(live_path, timeout=60)
        try:
            src.backup(dst)
            return
        except sqlite3.DatabaseError as exc:
            if 'locked' in str(exc).lower():
                raise
        finally:
            dst.close()
    finally:
        src.close()
    remove_db_files(live_path)
    shutil.copy2(source_path, live_path)
