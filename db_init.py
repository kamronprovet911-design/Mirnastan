import sqlite3
from werkzeug.security import generate_password_hash
import os
from dotenv import load_dotenv

load_dotenv()
DB = os.getenv('DATABASE', 'budget.db')

def ensure_column(conn, table_name, column_name, definition):
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')]
    if column_name not in columns:
        conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


def ensure_column(conn, table_name, column_name, definition):
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')]
    if column_name not in columns:
        conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        role TEXT,
        password_hash TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS kingdoms (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        budget REAL DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        key TEXT UNIQUE,
        value TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        from_user INTEGER,
        to_kingdom INTEGER,
        amount REAL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY,
        kingdom_id INTEGER,
        report_type TEXT,
        amount REAL,
        title TEXT,
        description TEXT,
        author_name TEXT,
        recipient_name TEXT,
        nickname TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        posted INTEGER DEFAULT 0
    )''')
    ensure_column(conn, 'reports', 'report_type', 'TEXT')
    ensure_column(conn, 'reports', 'title', 'TEXT')
    ensure_column(conn, 'reports', 'author_name', 'TEXT')
    ensure_column(conn, 'reports', 'recipient_name', 'TEXT')
    ensure_column(conn, 'reports', 'nickname', 'TEXT')
    conn.commit()

    # Seed kingdoms with starting budgets
    kingdoms = [
        ('Нердия', 1004000000.0),
        ('Астерион', 500000000.0),
        ('Мирноуль', 20000000.0),
    ]
    for k, budget in kingdoms:
        try:
            c.execute('INSERT INTO kingdoms (name, budget) VALUES (?,?)', (k, budget))
        except Exception:
            pass

    # Seed imperial treasury
    existing_treasury = c.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()
    if existing_treasury is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('treasury', '200000000000')")
    else:
        c.execute("UPDATE settings SET value='200000000000' WHERE key='treasury'")

    # Seed users
    users = [
        ('emperor','emperor','%s'),
        ('king_nerdia','king','%s'),
        ('king_asterion','king','%s'),
        ('king_mirnoul','king','%s'),
        ('graf_nerdia_1','graf','%s'),
        ('graf_asterion_1','graf','%s'),
        ('graf_mirnoul_1','graf','%s'),
    ]

    seeded = []
    for uname, role, _ in users:
        pw = f'{uname}_pass'
        ph = generate_password_hash(pw)
        try:
            c.execute('INSERT INTO users (username, role, password_hash) VALUES (?,?,?)', (uname, role, ph))
            seeded.append((uname,pw,role))
        except Exception:
            pass

    conn.commit()
    conn.close()
    print('Database initialized at', DB)
    print('Seeded users and passwords:')
    for u,p,r in seeded:
        print(f'- {u} ({r}): {p}')

if __name__ == '__main__':
    init_db()