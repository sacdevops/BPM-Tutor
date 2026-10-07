#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescue_sqlite.py — Rettet Daten aus einer beschädigten SQLite-Datenbank.

WICHTIG: Das Original wird NIEMALS verändert. Das Skript arbeitet
ausschließlich auf einer Kopie und schreibt die geretteten Daten in
eine neue Datei "<name>_rescued.db".

Verwendung:
    python rescue_sqlite.py "C:\\Users\\seyyi\\Downloads\\bpmtutor_backup_20260708_094353.db"

Optional:
    python rescue_sqlite.py <db-pfad> --out <ziel.db>

Strategie:
  1) Wenn die SQLite-CLI (sqlite3.exe) verfügbar ist: ".recover"
     (offizielles Recovery-Tool, rettet am meisten).
  2) Sonst: Python-Fallback, der jede Tabelle Zeile für Zeile ausliest.
     Beschädigte Bereiche werden per rowid einzeln abgetastet, sodass
     nur wirklich zerstörte Zeilen übersprungen werden.

Am Ende gibt es einen Bericht mit Zeilenzahlen pro Tabelle.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def make_working_copy(src: str) -> str:
    """Erstellt eine Arbeitskopie, damit das Original unangetastet bleibt."""
    tmpdir = tempfile.mkdtemp(prefix="sqlite_rescue_")
    dst = os.path.join(tmpdir, os.path.basename(src))
    shutil.copy2(src, dst)
    # Falls WAL/SHM-Dateien existieren, ebenfalls kopieren (können Daten enthalten!)
    for suffix in ("-wal", "-shm"):
        side = src + suffix
        if os.path.exists(side):
            shutil.copy2(side, dst + suffix)
            log(f"  Hinweis: {os.path.basename(side)} gefunden und mitkopiert "
                f"(kann noch nicht geschriebene Daten enthalten).")
    return dst


def find_sqlite_cli() -> str | None:
    """Sucht die sqlite3-Kommandozeile (sqlite3.exe unter Windows)."""
    for name in ("sqlite3", "sqlite3.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def table_counts(db_path: str) -> dict[str, int]:
    """Zählt Zeilen pro Tabelle (fehlertolerant)."""
    counts: dict[str, int] = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                counts[t] = n
            except sqlite3.DatabaseError:
                counts[t] = -1  # nicht zählbar (beschädigt)
        con.close()
    except sqlite3.DatabaseError:
        pass
    return counts


# ---------------------------------------------------------------------------
# Methode 1: Offizielles ".recover" der SQLite-CLI
# ---------------------------------------------------------------------------

def recover_with_cli(cli: str, damaged: str, out_db: str) -> bool:
    log("\n[Methode 1] Versuche Rettung mit sqlite3-CLI '.recover' ...")
    sql_dump = out_db + ".recover.sql"
    try:
        with open(sql_dump, "w", encoding="utf-8", errors="replace") as f:
            proc = subprocess.run(
                [cli, damaged, ".recover"],
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3600,
            )
        if proc.returncode not in (0, 1):  # .recover kann rc=1 liefern und trotzdem Daten retten
            log(f"  CLI beendet mit Code {proc.returncode}: {proc.stderr[:500]}")
        if os.path.getsize(sql_dump) < 50:
            log("  .recover hat (fast) nichts ausgegeben — Methode 1 fehlgeschlagen.")
            return False

        # Dump in neue Datenbank einspielen
        if os.path.exists(out_db):
            os.remove(out_db)
        con = sqlite3.connect(out_db)
        con.execute("PRAGMA foreign_keys=OFF;")
        with open(sql_dump, "r", encoding="utf-8", errors="replace") as f:
            script = f.read()
        try:
            con.executescript(script)
        except sqlite3.Error as e:
            # Manche .recover-Dumps enthalten einzelne kaputte Statements —
            # dann Statement für Statement einspielen und Fehler überspringen.
            log(f"  Gesamtimport fehlgeschlagen ({e}); versuche statementweise ...")
            con.close()
            if os.path.exists(out_db):
                os.remove(out_db)
            con = sqlite3.connect(out_db)
            con.execute("PRAGMA foreign_keys=OFF;")
            ok, bad = replay_statementwise(con, script)
            log(f"  Statementweise: {ok} ok, {bad} übersprungen.")
        con.commit()
        con.close()
        log(f"  Fertig. Recovery-SQL liegt zusätzlich hier: {sql_dump}")
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"  Methode 1 fehlgeschlagen: {e}")
        return False


def replay_statementwise(con: sqlite3.Connection, script: str) -> tuple[int, int]:
    """Spielt ein SQL-Skript Statement für Statement ein, überspringt Fehler."""
    ok = bad = 0
    stmt = ""
    for line in script.splitlines(keepends=True):
        stmt += line
        if sqlite3.complete_statement(stmt):
            try:
                con.execute(stmt)
                ok += 1
            except sqlite3.Error:
                bad += 1
            stmt = ""
    return ok, bad


# ---------------------------------------------------------------------------
# Methode 2: Python-Fallback — Zeile für Zeile retten
# ---------------------------------------------------------------------------

def get_schema(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Liest das Schema (type, name, sql) — mit Fallback über writable_schema."""
    try:
        rows = con.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return rows
    except sqlite3.DatabaseError:
        log("  sqlite_master direkt nicht lesbar — versuche es einzeln ...")
        rows = []
        try:
            names = con.execute(
                "SELECT rowid FROM sqlite_master"
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        for (rid,) in names:
            try:
                r = con.execute(
                    "SELECT type, name, sql FROM sqlite_master WHERE rowid=?",
                    (rid,),
                ).fetchone()
                if r and r[2]:
                    rows.append(r)
            except sqlite3.DatabaseError:
                continue
        return rows


def salvage_table(src: sqlite3.Connection, dst: sqlite3.Connection,
                  table: str) -> tuple[int, int]:
    """
    Kopiert eine Tabelle. Erst als Ganzes; scheitert das, per rowid einzeln.
    Rückgabe: (gerettete_zeilen, übersprungene_zeilen)
    """
    qt = table.replace('"', '""')
    # Spaltenanzahl ermitteln
    try:
        cols = src.execute(f'PRAGMA table_info("{qt}")').fetchall()
        ncols = len(cols)
    except sqlite3.DatabaseError:
        return (0, -1)
    if ncols == 0:
        return (0, 0)
    placeholders = ",".join("?" * ncols)
    insert_sql = f'INSERT OR IGNORE INTO "{qt}" VALUES ({placeholders})'

    saved = skipped = 0

    # 1) Schneller Versuch: alles am Stück (mit Iterator, nicht fetchall,
    #    damit wir bis zum Fehlerpunkt alles behalten)
    seen_rowids: set[int] = set()
    has_rowid = True
    try:
        cur = src.execute(f'SELECT rowid, * FROM "{qt}"')
    except sqlite3.DatabaseError:
        # WITHOUT ROWID Tabelle o.ä.
        has_rowid = False
        try:
            cur = src.execute(f'SELECT * FROM "{qt}"')
        except sqlite3.DatabaseError:
            cur = None

    if cur is not None:
        while True:
            try:
                row = cur.fetchone()
            except sqlite3.DatabaseError:
                break  # Beschädigung erreicht — weiter mit rowid-Scan
            if row is None:
                # Tabelle vollständig gelesen
                return (saved, skipped)
            if has_rowid:
                seen_rowids.add(row[0])
                data = row[1:]
            else:
                data = row
            try:
                dst.execute(insert_sql, data)
                saved += 1
            except sqlite3.Error:
                skipped += 1

    if not has_rowid:
        # Kein rowid-Scan möglich
        return (saved, skipped)

    # 2) rowid-Scan: max. rowid grob bestimmen, dann einzeln lesen
    max_rowid = None
    for probe in ("SELECT MAX(rowid) FROM \"%s\"" % qt,
                  "SELECT seq FROM sqlite_sequence WHERE name=?"):
        try:
            if "sqlite_sequence" in probe:
                r = src.execute(probe, (table,)).fetchone()
            else:
                r = src.execute(probe).fetchone()
            if r and r[0]:
                max_rowid = max(max_rowid or 0, int(r[0]))
        except sqlite3.DatabaseError:
            continue
    if max_rowid is None:
        max_rowid = (max(seen_rowids) if seen_rowids else 0) + 100_000
        log(f'    "{table}": max rowid unbekannt, scanne bis {max_rowid} ...')

    for rid in range(1, max_rowid + 1):
        if rid in seen_rowids:
            continue
        try:
            row = src.execute(
                f'SELECT * FROM "{qt}" WHERE rowid=?', (rid,)
            ).fetchone()
        except sqlite3.DatabaseError:
            skipped += 1
            continue
        if row is None:
            continue
        try:
            dst.execute(insert_sql, row)
            saved += 1
        except sqlite3.Error:
            skipped += 1

    return (saved, skipped)


def recover_with_python(damaged: str, out_db: str) -> bool:
    log("\n[Methode 2] Python-Fallback: Zeile-für-Zeile-Rettung ...")
    try:
        src = sqlite3.connect(f"file:{damaged}?mode=ro", uri=True)
    except sqlite3.DatabaseError as e:
        log(f"  Datenbank lässt sich gar nicht öffnen: {e}")
        return False

    # Recovery-freundliche Einstellungen
    for pragma in ("PRAGMA writable_schema=ON;",):
        try:
            src.execute(pragma)
        except sqlite3.DatabaseError:
            pass

    schema = get_schema(src)
    if not schema:
        log("  Konnte kein Schema lesen — Methode 2 fehlgeschlagen.")
        return False

    if os.path.exists(out_db):
        os.remove(out_db)
    dst = sqlite3.connect(out_db)
    dst.execute("PRAGMA foreign_keys=OFF;")
    dst.execute("PRAGMA journal_mode=OFF;")
    dst.execute("PRAGMA synchronous=OFF;")

    tables = [(n, s) for (t, n, s) in schema if t == "table"]
    others = [(t, n, s) for (t, n, s) in schema if t != "table"]

    # Tabellen anlegen
    for name, sql in tables:
        try:
            dst.execute(sql)
        except sqlite3.Error as e:
            log(f'  Warnung: Tabelle "{name}" konnte nicht angelegt werden: {e}')

    # Daten retten
    total_saved = total_skipped = 0
    for name, _ in tables:
        saved, skipped = salvage_table(src, dst, name)
        total_saved += max(saved, 0)
        if skipped > 0:
            total_skipped += skipped
        status = f"{saved} Zeilen gerettet"
        if skipped > 0:
            status += f", {skipped} beschädigt/übersprungen"
        elif skipped == -1:
            status = "Tabellenstruktur nicht lesbar"
        log(f'  "{name}": {status}')
        dst.commit()

    # Indizes, Trigger, Views zum Schluss (nicht kritisch, Fehler ok)
    for t, name, sql in others:
        try:
            dst.execute(sql)
        except sqlite3.Error:
            log(f"  Hinweis: {t} \"{name}\" konnte nicht wiederhergestellt "
                f"werden (unkritisch, kann neu erstellt werden).")

    dst.commit()
    dst.close()
    src.close()
    log(f"  Gesamt: {total_saved} Zeilen gerettet, "
        f"{total_skipped} Zeilen nicht lesbar.")
    return total_saved > 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Rettet eine beschädigte SQLite-DB.")
    ap.add_argument("db", help="Pfad zur beschädigten Datenbank")
    ap.add_argument("--out", help="Zielpfad für die gerettete DB (Standard: <name>_rescued.db)")
    args = ap.parse_args()

    src = os.path.abspath(args.db)
    if not os.path.exists(src):
        log(f"FEHLER: Datei nicht gefunden: {src}")
        return 1

    out_db = args.out or (os.path.splitext(src)[0] + "_rescued.db")
    out_db = os.path.abspath(out_db)
    if os.path.abspath(out_db) == src:
        log("FEHLER: Zieldatei darf nicht die Originaldatei sein.")
        return 1

    log(f"Original (bleibt unverändert): {src}")
    log(f"Ziel (gerettete Datenbank):    {out_db}")

    log("\nErstelle Arbeitskopie ...")
    work = make_working_copy(src)

    success = False
    cli = find_sqlite_cli()
    if cli:
        log(f"sqlite3-CLI gefunden: {cli}")
        success = recover_with_cli(cli, work, out_db)
    else:
        log("Keine sqlite3-CLI gefunden (das ist ok, Fallback wird genutzt).\n"
            "Tipp: Mit installierter CLI ist die Rettung oft vollständiger:\n"
            "  https://www.sqlite.org/download.html  (sqlite-tools für Windows)")

    if not success:
        success = recover_with_python(work, out_db)

    if not success:
        log("\nFEHLER: Keine Methode konnte Daten retten.")
        log("Das Original ist unverändert. Bitte NICHT weiter in die "
            "Original-DB schreiben. Nächste Option: sqlite3-CLI installieren "
            "und erneut versuchen.")
        return 2

    # Abschlussbericht
    log("\n" + "=" * 60)
    log("ERGEBNIS — Integritätsprüfung der geretteten Datenbank:")
    con = sqlite3.connect(out_db)
    try:
        res = con.execute("PRAGMA integrity_check;").fetchone()[0]
        log(f"  integrity_check: {res}")
    finally:
        con.close()

    log("\nZeilenzahlen (Original vs. gerettet):")
    orig_counts = table_counts(work)
    new_counts = table_counts(out_db)
    all_tables = sorted(set(orig_counts) | set(new_counts))
    for t in all_tables:
        o = orig_counts.get(t, None)
        n = new_counts.get(t, 0)
        o_str = "nicht zählbar" if o in (None, -1) else str(o)
        marker = ""
        if isinstance(o, int) and o >= 0 and n < o:
            marker = f"  <-- {o - n} Zeilen fehlen!"
        log(f'  {t}: Original={o_str}, Gerettet={n}{marker}')

    log(f"\nGerettete Datenbank: {out_db}")
    log("Das Original wurde nicht verändert. Bitte prüfe die Daten, "
        "bevor du die gerettete DB produktiv einsetzt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())