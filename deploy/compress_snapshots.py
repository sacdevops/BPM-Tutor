"""
BPM-Tutor — Compress existing task_bpmn_snapshots rows (local maintenance).
============================================================================
BPMN XML is highly repetitive; zlib typically shrinks it by 90-95 %.
New snapshots are compressed automatically by the app (bpmn_xml_z column).
This script migrates the EXISTING plain-text rows and reclaims disk space.

Designed for the download → fix locally → upload workflow:
  1. Admin → Settings → "Download database"
  2. python deploy/compress_snapshots.py --db path\\to\\bpmtutor_backup_*.db
  3. Admin → Settings → "Import database" (upload the same file again)

Steps performed:
  - Backs up the file first (*.pre-compress-<timestamp>.bak)
  - Adds the bpmn_xml_z BLOB column if missing
  - Compresses every row that still holds plain-text XML; empties the
    legacy bpmn_xml column (kept NOT NULL as '')
  - Runs VACUUM so the file actually shrinks

Uses only the Python standard library — no app environment needed.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import zlib
from datetime import datetime

BATCH = 500


def resolve_db_path(cli_path: str | None) -> str:
    if cli_path:
        path = cli_path
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_url = f'sqlite:///{os.path.join(base_dir, "data", "bpmtutor.db")}'
        db_url = os.getenv('DATABASE_URL', default_url)
        if not db_url.startswith('sqlite'):
            sys.exit('Only SQLite databases are supported. Use --db <file>.')
        path = db_url.split('///', 1)[1]
    if not os.path.isfile(path):
        sys.exit(f'Database file not found: {path}')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='Path to the SQLite file (default: DATABASE_URL / data/bpmtutor.db)')
    parser.add_argument('--dry-run', action='store_true', help='Only report, change nothing.')
    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    size_before = os.path.getsize(db_path)
    print(f'Database: {db_path} ({size_before / 1024 / 1024:.1f} MB)')

    if not args.dry_run:
        backup = f'{db_path}.pre-compress-{datetime.now().strftime("%Y%m%d_%H%M%S")}.bak'
        shutil.copy2(db_path, backup)
        print(f'Backup written to: {backup}')

    conn = sqlite3.connect(db_path)

    # Ensure schema columns added by recent code changes exist in the DB file.
    # This makes the script safe to run against a DB from before migrations.
    schema_patches = [
        ('task_bpmn_snapshots',  'bpmn_xml_z',    'BLOB'),
        ('research_participants', 'reinstated_at', 'DATETIME'),
    ]
    for tbl, col, typ in schema_patches:
        existing = [r[1] for r in conn.execute(f'PRAGMA table_info("{tbl}")')] 
        if col not in existing:
            print(f'Adding column {tbl}.{col} ({typ})...')
            if not args.dry_run:
                conn.execute(f'ALTER TABLE "{tbl}" ADD COLUMN "{col}" {typ}')

    # Ensure the bpmn_xml_z column exists
    cols = [r[1] for r in conn.execute('PRAGMA table_info("task_bpmn_snapshots")')]
    if not cols:
        sys.exit('Table task_bpmn_snapshots not found.')
    has_z = 'bpmn_xml_z' in cols

    count_sql = ("SELECT COUNT(*) FROM task_bpmn_snapshots "
                 "WHERE (bpmn_xml_z IS NULL OR length(bpmn_xml_z) = 0) "
                 "AND length(bpmn_xml) > 0")
    total = conn.execute(count_sql).fetchone()[0]
    print(f'Rows to compress: {total}')

    if args.dry_run:
        conn.close()
        print('Dry run - nothing changed.')
        return

    done = 0
    bytes_in = 0
    bytes_out = 0
    while True:
        rows = conn.execute(
            'SELECT id, bpmn_xml FROM task_bpmn_snapshots '
            'WHERE (bpmn_xml_z IS NULL OR length(bpmn_xml_z) = 0) '
            'AND length(bpmn_xml) > 0 LIMIT ?', (BATCH,)
        ).fetchall()
        if not rows:
            break
        for row_id, xml in rows:
            data = xml.encode('utf-8') if isinstance(xml, str) else bytes(xml)
            comp = zlib.compress(data, 6)
            bytes_in += len(data)
            bytes_out += len(comp)
            conn.execute(
                "UPDATE task_bpmn_snapshots SET bpmn_xml_z = ?, bpmn_xml = '' WHERE id = ?",
                (sqlite3.Binary(comp), row_id),
            )
        conn.commit()
        done += len(rows)
        print(f'  {done}/{total} rows...', end='\r')

    print(f'\nCompressed {done} rows: {bytes_in / 1024 / 1024:.1f} MB -> {bytes_out / 1024 / 1024:.1f} MB')

    print('Running VACUUM (this may take a moment)...')
    conn.execute('VACUUM')
    conn.close()

    size_after = os.path.getsize(db_path)
    print(f'File size: {size_before / 1024 / 1024:.1f} MB -> {size_after / 1024 / 1024:.1f} MB')


if __name__ == '__main__':
    main()
