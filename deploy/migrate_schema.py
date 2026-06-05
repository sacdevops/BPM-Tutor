"""
BPM-Tutor — Safe Schema Migration Script
=========================================
Compares the live database against the SQLAlchemy model definitions and:
  - Creates missing tables (with all columns + indexes)
  - Adds missing columns to existing tables
  - Reports extra columns/tables (never drops anything automatically)

Safe to run on a production database at any time.
Run from the project root:
    python deploy/migrate_schema.py [--drop-extras]

Options:
    --drop-extras   Also DROP columns that exist in the DB but not in models
                    (USE WITH CAUTION — back up first!)
    --dry-run       Print what would be done without changing anything
"""

import sys
import os
import argparse
import logging

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

# ── Colour helpers (Windows-safe fallback) ────────────────────────────────────
try:
    import colorama
    colorama.init()
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    CYAN   = '\033[96m'
    RESET  = '\033[0m'
    BOLD   = '\033[1m'
except ImportError:
    GREEN = YELLOW = RED = CYAN = RESET = BOLD = ''


def _hdr(msg: str) -> str:
    return f'{BOLD}{CYAN}{msg}{RESET}'

def _ok(msg: str) -> str:
    return f'{GREEN}✓ {msg}{RESET}'

def _warn(msg: str) -> str:
    return f'{YELLOW}⚠ {msg}{RESET}'

def _err(msg: str) -> str:
    return f'{RED}✗ {msg}{RESET}'


# ── Column DDL helpers ────────────────────────────────────────────────────────

def _compile_type(col_type, dialect) -> str:
    """Compile a SQLAlchemy type to its dialect-specific SQL string."""
    try:
        return col_type.compile(dialect=dialect)
    except Exception:
        return 'TEXT'


def _default_clause(col, dialect_name: str) -> str:
    """
    Return a DEFAULT clause string for ALTER TABLE ADD COLUMN.

    Rules:
    - Use the column's server_default if set (raw SQL fragment).
    - Use the column's Python-level default if it's a scalar.
    - For NOT NULL columns with no default, infer a safe zero-value
      so the ADD COLUMN succeeds on tables with existing rows.
    - For nullable columns, fall back to NULL.
    """
    # Explicit server default (raw SQL, e.g. "now()", "0", "''")
    if col.server_default is not None:
        raw = str(col.server_default.arg)
        return f'DEFAULT {raw}'

    # Python-level scalar default
    if col.default is not None and hasattr(col.default, 'arg'):
        arg = col.default.arg
        if callable(arg):
            pass  # callable defaults can't be expressed as SQL literals
        elif isinstance(arg, bool):
            return f"DEFAULT {'1' if arg else '0'}"
        elif isinstance(arg, (int, float)):
            return f'DEFAULT {arg}'
        elif isinstance(arg, str):
            escaped = arg.replace("'", "''")
            return f"DEFAULT '{escaped}'"

    # No explicit default — use a safe sentinel
    if col.nullable:
        return 'DEFAULT NULL'

    # NOT NULL without default: infer by Python type
    try:
        pt = col.type.python_type
        if pt in (bool, int):
            return 'DEFAULT 0'
        if pt == float:
            return 'DEFAULT 0.0'
        return "DEFAULT ''"
    except NotImplementedError:
        return 'DEFAULT NULL'


def _build_add_column_sql(table_name: str, col, dialect, dialect_name: str) -> str:
    """
    Build the ALTER TABLE … ADD COLUMN … statement.
    PostgreSQL supports full constraint syntax; SQLite is more limited.
    """
    type_str  = _compile_type(col.type, dialect)
    default   = _default_clause(col, dialect_name)
    nullable  = '' if col.nullable else ' NOT NULL'

    if dialect_name == 'postgresql':
        # Postgres: add with default first, then remove default if unwanted
        return (
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN IF NOT EXISTS "{col.name}" {type_str} {default}{nullable}'
        )
    else:
        # SQLite: ADD COLUMN, no NOT NULL without default in existing tables
        # We always supply a default so it works on non-empty tables.
        return f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {type_str} {default}'


def _build_drop_column_sql(table_name: str, col_name: str, dialect_name: str) -> str:
    if dialect_name == 'sqlite':
        # SQLite < 3.35 doesn't support DROP COLUMN — check at runtime
        return f'ALTER TABLE "{table_name}" DROP COLUMN "{col_name}"'
    return f'ALTER TABLE "{table_name}" DROP COLUMN "{col_name}"'


# ── Core migration logic ──────────────────────────────────────────────────────

# Tables that are managed externally and should never be touched
SKIP_TABLES = {'alembic_version'}


def run_migration(drop_extras: bool = False, dry_run: bool = False) -> bool:
    """
    Return True if everything succeeded (or nothing needed doing).
    """
    from app import create_app
    from app.extensions import db
    from sqlalchemy import inspect, text

    app = create_app()
    ok = True

    with app.app_context():
        engine      = db.engine
        dialect     = engine.dialect
        dialect_name = dialect.name  # 'sqlite' or 'postgresql'
        inspector   = inspect(engine)
        model_meta  = db.metadata

        print(_hdr('\n══════════════════════════════════════════════════'))
        print(_hdr('  BPM-Tutor Schema Migration'))
        print(_hdr(f'  Database: {dialect_name.upper()}  |  dry_run={dry_run}'))
        print(_hdr('══════════════════════════════════════════════════\n'))

        stats = dict(
            tables_created=0, tables_skipped=0,
            cols_added=0, cols_failed=0,
            cols_dropped=0, cols_drop_failed=0,
            extra_tables=[], extra_cols=[]
        )

        existing_tables = set(inspector.get_table_names())

        # ── 1. Create completely missing tables ───────────────────────────
        print(_hdr('[ 1/3 ] Checking tables …'))
        for tname in sorted(model_meta.tables):
            if tname in SKIP_TABLES:
                continue
            if tname not in existing_tables:
                print(f'  {_ok(f"CREATE TABLE  {tname}")}')
                if not dry_run:
                    try:
                        model_meta.tables[tname].create(bind=engine, checkfirst=True)
                        stats['tables_created'] += 1
                    except Exception as exc:
                        print(f'  {_err(f"FAILED: {exc}")}')
                        ok = False
                else:
                    stats['tables_created'] += 1
            else:
                stats['tables_skipped'] += 1

        # ── 2. Add missing columns to existing tables ─────────────────────
        # Refresh inspector after possible table creation
        inspector = inspect(engine)
        print(_hdr('\n[ 2/3 ] Checking columns …'))

        for tname, table in sorted(model_meta.tables.items()):
            if tname in SKIP_TABLES:
                continue
            if tname not in inspector.get_table_names():
                continue  # was just created above — all columns already there

            existing_cols = {c['name'] for c in inspector.get_columns(tname)}

            for col in table.columns:
                if col.name in existing_cols:
                    continue

                sql = _build_add_column_sql(tname, col, dialect, dialect_name)
                print(f'  {_ok(f"ADD COLUMN  {tname}.{col.name}")}')
                if not dry_run:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(sql))
                        stats['cols_added'] += 1
                    except Exception as exc:
                        print(f'    {_err(f"FAILED: {exc}")}')
                        print(f'    SQL was: {sql}')
                        stats['cols_failed'] += 1
                        ok = False
                else:
                    stats['cols_added'] += 1

        # ── 3. Report (and optionally drop) extra columns ─────────────────
        print(_hdr('\n[ 3/3 ] Checking for extra columns …'))
        inspector = inspect(engine)

        for tname in sorted(inspector.get_table_names()):
            if tname in SKIP_TABLES:
                continue
            if tname not in model_meta.tables:
                stats['extra_tables'].append(tname)
                print(f'  {_warn(f"EXTRA TABLE  {tname}  (not in models — kept)")}')
                continue

            model_col_names = {c.name for c in model_meta.tables[tname].columns}
            db_col_names    = {c['name'] for c in inspector.get_columns(tname)}
            extras          = sorted(db_col_names - model_col_names)

            for col_name in extras:
                stats['extra_cols'].append(f'{tname}.{col_name}')
                if drop_extras:
                    sql = _build_drop_column_sql(tname, col_name, dialect_name)
                    print(f'  {_warn(f"DROP COLUMN  {tname}.{col_name}")}')
                    if not dry_run:
                        try:
                            with engine.begin() as conn:
                                conn.execute(text(sql))
                            stats['cols_dropped'] += 1
                        except Exception as exc:
                            print(f'    {_err(f"FAILED: {exc}")}')
                            stats['cols_drop_failed'] += 1
                    else:
                        stats['cols_dropped'] += 1
                else:
                    print(f'  {_warn(f"EXTRA COLUMN {tname}.{col_name}  (not in model — kept)")}')

        # ── Summary ───────────────────────────────────────────────────────
        print(_hdr('\n══════════════════════════════════════════════════'))
        print(_hdr('  Summary'))
        print(_hdr('══════════════════════════════════════════════════'))
        mode = ' [DRY RUN]' if dry_run else ''
        print(f'  Tables created:    {stats["tables_created"]}{mode}')
        print(f'  Tables unchanged:  {stats["tables_skipped"]}')
        print(f'  Columns added:     {stats["cols_added"]}{mode}')
        print(f'  Columns failed:    {stats["cols_failed"]}')
        if drop_extras:
            print(f'  Columns dropped:   {stats["cols_dropped"]}{mode}')
            print(f'  Drop failures:     {stats["cols_drop_failed"]}')
        print(f'  Extra tables:      {len(stats["extra_tables"])}')
        print(f'  Extra columns:     {len(stats["extra_cols"])}')

        if stats['extra_cols'] and not drop_extras:
            print(f'\n  {_warn("Run with --drop-extras to remove extra columns.")}')

        if ok and stats['cols_failed'] == 0:
            print(f'\n{_ok("Migration completed successfully.")}')
        else:
            print(f'\n{_err("Migration completed with errors — review output above.")}')

        print(_hdr('══════════════════════════════════════════════════\n'))
        return ok


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='BPM-Tutor safe schema migration tool'
    )
    parser.add_argument(
        '--drop-extras',
        action='store_true',
        help='Drop DB columns that no longer exist in the models (USE WITH CAUTION)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making any changes'
    )
    args = parser.parse_args()

    if args.drop_extras and not args.dry_run:
        print(_warn(
            '\nWARNING: --drop-extras will permanently delete columns from the database.\n'
            'Make sure you have a backup before proceeding.\n'
        ))
        confirm = input('Type YES to continue: ').strip()
        if confirm != 'YES':
            print('Aborted.')
            sys.exit(0)

    success = run_migration(
        drop_extras=args.drop_extras,
        dry_run=args.dry_run
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
