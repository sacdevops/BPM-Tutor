"""
BPM-Tutor — Repair corrupted DB cells caused by the old DB-Inspector bug.
==========================================================================
The old inline cell editor wrote broken HTML fragments (e.g.
  NULL" onclick="dbiEditCell(this)" style="cursor:pointer">NULL
) and empty strings '' into cells instead of SQL NULL. Empty strings in
DATETIME columns crash SQLAlchemy when loading rows (→ 500 errors).

This script:
  1. Backs up the SQLite database file first.
  2. Sets every cell containing the known editor junk pattern to NULL.
  3. Sets unparseable / empty-string values in DATETIME columns to NULL.
  4. Normalises empty-string dropout_reason values to NULL (uniformity).

Usage (from project root):
    python deploy/fix_corrupted_cells.py [--dry-run] [--db path\to\file.db]

Without --db the path is resolved from DATABASE_URL / data/bpmtutor.db.
With --db you can run it against a downloaded copy of the server database
(Admin → Settings → Download database, fix locally, upload again).
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 'dbiEditCell' is unique to the buggy inspector markup and cannot occur
# in legitimate content — do NOT broaden this (e.g. to 'onclick='), or
# legitimate HTML stored in other tables could be wiped.
JUNK_MARKERS = ('dbiEditCell',)
DT_RE = re.compile(r'^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$')


def resolve_db_path(cli_path=None) -> str:
    """Resolve the SQLite file path (--db overrides DATABASE_URL/default)."""
    if cli_path:
        if not os.path.isfile(cli_path):
            sys.exit(f'Database file not found: {cli_path}')
        return cli_path
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_url = f'sqlite:///{os.path.join(base_dir, "data", "bpmtutor.db")}'
    db_url = os.getenv('DATABASE_URL', default_url)
    if not db_url.startswith('sqlite'):
        sys.exit('Only SQLite databases are supported by this script.')
    path = db_url.split('///', 1)[1]
    if not os.path.isfile(path):
        sys.exit(f'Database file not found: {path}')
    return path


def is_junk(value) -> bool:
    return isinstance(value, str) and any(m in value for m in JUNK_MARKERS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='Only report what would be changed.')
    parser.add_argument('--db', help='Path to the SQLite file (default: DATABASE_URL / data/bpmtutor.db)')
    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    print(f'Database: {db_path}')

    if not args.dry_run:
        backup = f'{db_path}.pre-fix-{datetime.now().strftime("%Y%m%d_%H%M%S")}.bak'
        shutil.copy2(db_path, backup)
        print(f'Backup written to: {backup}')

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total_fixes = 0

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    )]

    for table in tables:
        cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        pk_cols = [c['name'] for c in cols if c['pk']]
        if len(pk_cols) != 1:
            continue  # only single-PK tables (all app tables have one)
        pk = pk_cols[0]

        dt_cols = [c['name'] for c in cols
                   if 'DATE' in (c['type'] or '').upper() or
                      'TIME' in (c['type'] or '').upper()]
        reason_cols = [c['name'] for c in cols if c['name'] == 'dropout_reason']
        check_cols = [c['name'] for c in cols if c['name'] != pk]
        if not check_cols:
            continue

        rows = conn.execute(
            f'SELECT "{pk}", {", ".join(f_quoted(c) for c in check_cols)} '
            f'FROM "{table}"'
        ).fetchall()

        for row in rows:
            for col in check_cols:
                val = row[col]
                if val is None or not isinstance(val, str):
                    continue
                reason = None
                if is_junk(val):
                    reason = 'editor junk'
                elif col in dt_cols and (val.strip() == '' or not DT_RE.match(val.strip())):
                    reason = 'invalid datetime'
                elif col in reason_cols and val.strip() == '':
                    reason = 'empty string -> NULL'
                if reason:
                    total_fixes += 1
                    print(f'  {table}.{col} ({pk}={row[pk]}): {reason} - {val[:60]!r}')
                    if not args.dry_run:
                        conn.execute(
                            f'UPDATE "{table}" SET "{col}" = NULL WHERE "{pk}" = ?',
                            (row[pk],),
                        )

    if not args.dry_run:
        conn.commit()
    conn.close()

    verb = 'Would fix' if args.dry_run else 'Fixed'
    print(f'\n{verb} {total_fixes} cell(s).')
    if total_fixes and args.dry_run:
        print('Run again without --dry-run to apply.')


def f_quoted(name: str) -> str:
    return f'"{name}"'


if __name__ == '__main__':
    main()
