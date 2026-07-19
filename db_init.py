import sqlite3
from werkzeug.security import generate_password_hash
import os
from dotenv import load_dotenv

load_dotenv()
DB = os.getenv('DATABASE', 'budget.db')

def default_kingdom_for_username(username):
    kingdom_map = {
        'king_nerdia': 'Нердия',
        'king_asterion': 'Астерион',
        'king_mirnoul': 'Мирноуль',
        'graf_nerdia_1': 'Нердия',
        'graf_asterion_1': 'Астерион',
        'graf_mirnoul_1': 'Мирноуль',
    }
    return kingdom_map.get(username)


DEFAULT_COUNTIES = [
    ('Астерион', 'Мирнополь', 'graf_asterion_1', 'Столица и центр власти', 50, 54),
    ('Астерион', 'Ауреград', 'graf_asterion_auregrad', 'Город знати и дворцов', 52, 35),
    ('Астерион', 'Златоречье', 'graf_asterion_zlatorechye', 'Торговый город на реке', 33, 63),
    ('Астерион', 'Вестгард', 'graf_asterion_vestgard', 'Западная крепость', 33, 20),
    ('Астерион', 'Солнечный Берег', 'graf_asterion_sunny_coast', 'Портовый город', 17, 50),
    ('Нердия', 'Нердбург', 'graf_nerdia_1', 'Столица науки и управления', 48, 49),
    ('Нердия', 'Железноград', 'graf_nerdia_zhelezograd', 'Металлургический город', 68, 38),
    ('Нердия', 'Кристалхейм', 'graf_nerdia_kristalheim', 'Город шахтёров и кристаллов', 25, 34),
    ('Нердия', 'Фордхолл', 'graf_nerdia_fordholl', 'Оружейный центр', 32, 58),
    ('Нердия', 'Северный Дозор', 'graf_nerdia_north_watch', 'Северная крепость', 45, 18),
    ('Нердия', 'Южный Щит', 'graf_nerdia_south_shield', 'Южный форпост', 67, 72),
    ('Мирноуль', 'Мирноуль', 'graf_mirnoul_1', 'Столица провинции', 50, 48),
    ('Мирноуль', 'Зеленодар', 'graf_mirnoul_zelenodar', 'Сельскохозяйственный центр', 31, 28),
    ('Мирноуль', 'Риверфолл', 'graf_mirnoul_riverfall', 'Речной торговый город', 69, 49),
    ('Мирноуль', 'Лесоград', 'graf_mirnoul_lesograd', 'Лесозаготовка и ремёсла', 68, 29),
    ('Мирноуль', 'Озерск', 'graf_mirnoul_ozersk', 'Курортный город у озера', 56, 18),
    ('Мирноуль', 'Полевик', 'graf_mirnoul_polevik', 'Город хлеборобов', 35, 63),
    ('Мирноуль', 'Солнечный Луг', 'graf_mirnoul_sunny_meadow', 'Ярмарки и сыроварни', 26, 46),
    ('Мирноуль', 'Долинный Мост', 'graf_mirnoul_valley_bridge', 'Пограничный мост', 42, 70),
    ('Мирноуль', 'Травозёр', 'graf_mirnoul_travozer', 'Лекарственные травы', 66, 66),
]


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
        password_hash TEXT,
        balance REAL DEFAULT 0,
        daily_income REAL DEFAULT 0,
        kingdom_name TEXT DEFAULT '',
        county_name TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS kingdoms (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        budget REAL DEFAULT 0,
        daily_income REAL DEFAULT 0,
        map_image TEXT DEFAULT '',
        map_notes TEXT DEFAULT ''
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
    c.execute('''CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        card_type TEXT DEFAULT 'action',
        rarity TEXT DEFAULT 'common',
        effect TEXT DEFAULT '',
        owner_id INTEGER,
        for_trade INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS imperial_council (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        council_income REAL DEFAULT 0,
        note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS counties (
        id INTEGER PRIMARY KEY,
        kingdom_name TEXT,
        name TEXT,
        graf_user_id INTEGER,
        map_hint TEXT DEFAULT '',
        map_x REAL DEFAULT 50,
        map_y REAL DEFAULT 50,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(kingdom_name, name)
    )''')

    # resource stocks on kingdoms
    ensure_column(conn, 'kingdoms', 'tree', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'metal', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'food', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'tree_income', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'metal_income', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'food_income', 'REAL DEFAULT 0')

    c.execute('''CREATE TABLE IF NOT EXISTS building_requests (
        id INTEGER PRIMARY KEY,
        kingdom_id INTEGER,
        kingdom_name TEXT,
        county_id INTEGER,
        county_name TEXT,
        requested_by_user_id INTEGER,
        requested_by_username TEXT,
        requested_by_role TEXT,
        item_name TEXT,
        requested_tree_cost REAL DEFAULT 0,
        requested_metal_cost REAL DEFAULT 0,
        requested_food_cost REAL DEFAULT 0,
        requested_kingdom_cash_cost REAL DEFAULT 0,
        treasury_cash_covered REAL DEFAULT 0,
        kingdom_cash_cost REAL DEFAULT 0,
        proposed_tree_income REAL DEFAULT 0,
        proposed_metal_income REAL DEFAULT 0,
        proposed_food_income REAL DEFAULT 0,
        status TEXT DEFAULT 'submitted',
        reason TEXT DEFAULT '',
        approved_by_user_id INTEGER,
        approved_by_username TEXT,
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    ensure_column(conn, 'reports', 'report_type', 'TEXT')
    ensure_column(conn, 'reports', 'title', 'TEXT')
    ensure_column(conn, 'reports', 'author_name', 'TEXT')
    ensure_column(conn, 'reports', 'recipient_name', 'TEXT')
    ensure_column(conn, 'reports', 'nickname', 'TEXT')
    ensure_column(conn, 'users', 'balance', 'REAL DEFAULT 0')
    ensure_column(conn, 'users', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(conn, 'users', 'kingdom_name', "TEXT DEFAULT ''")
    ensure_column(conn, 'users', 'county_name', "TEXT DEFAULT ''")
    ensure_column(conn, 'kingdoms', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(conn, 'kingdoms', 'map_image', "TEXT DEFAULT ''")
    ensure_column(conn, 'kingdoms', 'map_notes', "TEXT DEFAULT ''")
    ensure_column(conn, 'cards', 'description', "TEXT DEFAULT ''")
    ensure_column(conn, 'cards', 'card_type', "TEXT DEFAULT 'action'")
    ensure_column(conn, 'cards', 'rarity', "TEXT DEFAULT 'common'")
    ensure_column(conn, 'cards', 'effect', "TEXT DEFAULT ''")
    ensure_column(conn, 'cards', 'owner_id', 'INTEGER')
    ensure_column(conn, 'cards', 'for_trade', 'INTEGER DEFAULT 0')
    ensure_column(conn, 'imperial_council', 'council_income', 'REAL DEFAULT 0')
    ensure_column(conn, 'imperial_council', 'note', "TEXT DEFAULT ''")
    ensure_column(conn, 'counties', 'graf_user_id', 'INTEGER')
    ensure_column(conn, 'counties', 'map_hint', "TEXT DEFAULT ''")
    ensure_column(conn, 'counties', 'map_x', 'REAL DEFAULT 50')
    ensure_column(conn, 'counties', 'map_y', 'REAL DEFAULT 50')
    conn.commit()

    # Seed missing defaults only. Existing budgets, treasury and users are preserved.
    kingdoms = [
        ('Нердия', 1004000000.0, 'maps/nerdia.jpg', 'Промышленное сердце Мирнастана: шахты, крепости, горные перевалы и северная оборона.'),
        ('Астерион', 500000000.0, 'maps/asterion.jpg', 'Центральная провинция Империи: столица, торговые тракты, порты и плодородные равнины.'),
        ('Мирноуль', 20000000.0, 'maps/mirnoul.jpg', 'Житница и лесной край: поля, реки, озёра, лечебные травы и южные дороги.'),
    ]
    for name, budget, map_image, map_notes in kingdoms:
        c.execute('INSERT OR IGNORE INTO kingdoms (name, budget, map_image, map_notes) VALUES (?,?,?,?)', (name, budget, map_image, map_notes))
        c.execute(
            '''UPDATE kingdoms
               SET map_image = COALESCE(NULLIF(map_image, ''), ?),
                   map_notes = COALESCE(NULLIF(map_notes, ''), ?)
               WHERE name=?''',
            (map_image, map_notes, name),
        )

    existing_treasury = c.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()
    if existing_treasury is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('treasury', '10000000000')")
    if c.execute("SELECT value FROM settings WHERE key='daily_income_last_date'").fetchone() is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('daily_income_last_date', '')")
    if c.execute("SELECT value FROM settings WHERE key='empire_map_image'").fetchone() is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('empire_map_image', 'maps/mirnastan.jpg')")
    if c.execute("SELECT value FROM settings WHERE key='empire_map_notes'").fetchone() is None:
        c.execute("INSERT INTO settings (key, value) VALUES ('empire_map_notes', 'Общая карта империи с тремя провинциями: Астерион, Нердия и Мирноуль.')")

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
            c.execute('INSERT INTO users (username, role, password_hash, kingdom_name) VALUES (?,?,?,?)', (uname, role, ph, default_kingdom_for_username(uname) or ''))
            seeded.append((uname,pw,role))
        except Exception:
            pass
        kingdom_name = default_kingdom_for_username(uname)
        if kingdom_name:
            c.execute(
                "UPDATE users SET kingdom_name = COALESCE(NULLIF(kingdom_name, ''), ?) WHERE username=?",
                (kingdom_name, uname),
            )

    for kingdom_name, county_name, username, map_hint, map_x, map_y in DEFAULT_COUNTIES:
        row = c.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if row is None:
            c.execute(
                'INSERT INTO users (username, role, password_hash, kingdom_name, county_name) VALUES (?,?,?,?,?)',
                (username, 'graf', generate_password_hash(f'{username}_pass'), kingdom_name, county_name),
            )
            row = c.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        else:
            c.execute(
                "UPDATE users SET role='graf', kingdom_name=COALESCE(NULLIF(kingdom_name, ''), ?), county_name=COALESCE(NULLIF(county_name, ''), ?) WHERE username=?",
                (kingdom_name, county_name, username),
            )
        c.execute(
            'INSERT OR IGNORE INTO counties (kingdom_name, name, graf_user_id, map_hint, map_x, map_y) VALUES (?,?,?,?,?,?)',
            (kingdom_name, county_name, row[0], map_hint, map_x, map_y),
        )
        c.execute(
            '''UPDATE counties
               SET graf_user_id=COALESCE(graf_user_id, ?),
                   map_hint=COALESCE(NULLIF(map_hint, ''), ?),
                   map_x=COALESCE(map_x, ?),
                   map_y=COALESCE(map_y, ?)
               WHERE kingdom_name=? AND name=?''',
            (row[0], map_hint, map_x, map_y, kingdom_name, county_name),
        )

    conn.commit()
    conn.close()
    print('Database initialized at', DB)
    print('Seeded users and passwords:')
    for u,p,r in seeded:
        print(f'- {u} ({r}): {p}')

if __name__ == '__main__':
    init_db()
