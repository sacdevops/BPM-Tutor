"""
One-time migration: add all columns introduced in the new feature set.
Safe to run multiple times — each ALTER TABLE is wrapped in a try/except.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'bpmtutor.db')

MIGRATIONS = [
    # users
    "ALTER TABLE users ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'de'",

    # task_submissions – grading annotations
    "ALTER TABLE task_submissions ADD COLUMN grade_annotations TEXT",

    # task_submissions – AI grade suggestion
    "ALTER TABLE task_submissions ADD COLUMN ai_grade_value REAL",
    "ALTER TABLE task_submissions ADD COLUMN ai_grade_passed BOOLEAN",
    "ALTER TABLE task_submissions ADD COLUMN ai_grade_comment TEXT",
    "ALTER TABLE task_submissions ADD COLUMN ai_grade_annotations TEXT",
    "ALTER TABLE task_submissions ADD COLUMN ai_grade_generated_at DATETIME",

    # task_submissions – AI mentor memory + analytics
    "ALTER TABLE task_submissions ADD COLUMN mentor_memory TEXT",
    "ALTER TABLE task_submissions ADD COLUMN phase_counts TEXT",
    "ALTER TABLE task_submissions ADD COLUMN validation_error_keys TEXT",
]


def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    applied = 0
    skipped = 0
    for sql in MIGRATIONS:
        try:
            cur.execute(sql)
            conn.commit()
            col = sql.split("ADD COLUMN")[1].strip().split()[0]
            print(f"  [OK]      {col}")
            applied += 1
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                col = sql.split("ADD COLUMN")[1].strip().split()[0]
                print(f"  [SKIP]    {col} (already exists)")
                skipped += 1
            else:
                print(f"  [ERROR]   {sql}\n           {e}")
    conn.close()
    print(f"\nDone: {applied} applied, {skipped} skipped.")


if __name__ == '__main__':
    print(f"Migrating: {DB_PATH}")
    run()
