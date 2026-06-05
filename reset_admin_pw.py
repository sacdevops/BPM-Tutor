"""
Utility script: list admin users and optionally reset the password.
Run with:  python reset_admin_pw.py
"""
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "data/bpmtutor.db"

conn = sqlite3.connect(DB_PATH)

print("=== Admin users ===")
rows = conn.execute(
    "SELECT id, username, email, role FROM users WHERE role='admin'"
).fetchall()
for r in rows:
    print(r)

# --- Uncomment and fill in to reset a password ---
NEW_PASSWORD = "admin1234"
TARGET_USERNAME = "admin"  # or use email
hashed = generate_password_hash(NEW_PASSWORD)
conn.execute(
    "UPDATE users SET password_hash = ? WHERE username = ?",
    (hashed, TARGET_USERNAME)
)
conn.commit()
print(f"Password for '{TARGET_USERNAME}' has been reset.")

conn.close()
