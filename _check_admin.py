import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash

DB = "data/bpmtutor.db"
conn = sqlite3.connect(DB)

cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
rows = conn.execute("SELECT * FROM users WHERE role='admin'").fetchall()

for row in rows:
    d = dict(zip(cols, row))
    print("id          :", d['id'])
    print("username    :", d['username'])
    print("email       :", d['email'])
    print("is_active   :", d['is_active'])
    print("is_locked   :", d['is_locked'])
    print("is_verified :", d['is_verified'])
    pw_ok = check_password_hash(d['password_hash'], 'admin1234')
    print("pw 'admin1234' valid:", pw_ok)
    print()

# If not active/verified, fix it
conn.execute("UPDATE users SET is_active=1, is_locked=0, is_verified=1 WHERE role='admin'")
conn.commit()
print("-> is_active=1, is_locked=0, is_verified=1 set for all admins.")
conn.close()
