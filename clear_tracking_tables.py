"""
Clears table contents and selected column values from a SQLite database file.
"""

import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox


TABLES_TO_CLEAR = [
    "task_session_tracking",
    "task_bpmn_snapshots",
    "survey_responses",
    "survey_questions",
]

# (table, column) pairs where only the column value is set to NULL
COLUMNS_TO_CLEAR = [
    ("task_submissions", "llm_prompt_log"),
]


def select_database() -> str | None:
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Datenbank auswählen",
        filetypes=[("SQLite Datenbank", "*.db *.sqlite *.sqlite3"), ("Alle Dateien", "*.*")],
    )
    root.destroy()
    return path or None


def get_row_count(cursor: sqlite3.Cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
    return cursor.fetchone()[0]


def clear_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # Verify tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {row[0] for row in cursor.fetchall()}

        results = []
        for table in TABLES_TO_CLEAR:
            if table not in existing:
                results.append(f"  - {table}: Tabelle nicht gefunden, übersprungen.")
                continue
            count = get_row_count(cursor, table)
            cursor.execute(f"DELETE FROM [{table}]")
            results.append(f"  - {table}: {count} Zeile(n) gelöscht.")

        for table, column in COLUMNS_TO_CLEAR:
            if table not in existing:
                results.append(f"  - {table}.{column}: Tabelle nicht gefunden, übersprungen.")
                continue
            cursor.execute(
                f"SELECT COUNT(*) FROM [{table}] WHERE [{column}] IS NOT NULL"
            )
            count = cursor.fetchone()[0]
            cursor.execute(f"UPDATE [{table}] SET [{column}] = NULL")
            results.append(f"  - {table}.{column}: {count} Zeile(n) auf NULL gesetzt.")

        conn.commit()

        # Reclaim unused space so the file actually shrinks on disk
        conn.execute("VACUUM")

        summary = "\n".join(results)
        messagebox.showinfo(
            "Fertig",
            f"Datenbank: {db_path}\n\nErgebnis:\n{summary}\n\nVACUUM ausgeführt – Datei wurde komprimiert.",
        )
    except Exception as exc:
        conn.rollback()
        messagebox.showerror("Fehler", f"Fehler beim Löschen:\n{exc}")
    finally:
        conn.close()


def main() -> None:
    db_path = select_database()
    if not db_path:
        print("Keine Datenbank ausgewählt. Abbruch.")
        return

    root = tk.Tk()
    root.withdraw()
    confirmed = messagebox.askyesno(
        "Bestätigung",
        f"Sollen folgende Daten aus der Datenbank\n\n  {db_path}\n\n"
        f"unwiderruflich entfernt werden?\n\n"
        f"Tabellen (alle Zeilen):\n  {chr(10).join(TABLES_TO_CLEAR)}\n\n"
        f"Spalten (auf NULL setzen):\n  "
        f"{chr(10).join(f'{t}.{c}' for t, c in COLUMNS_TO_CLEAR)}",

    )
    root.destroy()

    if not confirmed:
        print("Abgebrochen.")
        return

    clear_tables(db_path)


if __name__ == "__main__":
    main()
