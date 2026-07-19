import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
DB_PATH = os.getenv('DATABASE', 'budget.db')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'dev-secret')

APP_TIMEZONE = os.getenv('APP_TIMEZONE') or os.getenv('TZ')
DAILY_INCOME_HOUR = 0
DAILY_INCOME_MINUTE = 1
DAILY_INCOME_LAST_DATE_KEY = 'daily_income_last_date'
AUTHORITY_ROLES = ('emperor',)
DEFAULT_TREASURY = 5000000000.0
MAP_UPLOAD_FOLDER = os.path.join(app.static_folder, 'maps')
ALLOWED_MAP_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

DEFAULT_KINGDOMS = [
    ('Нердия', 1004000000.0, 'maps/nerdia.jpg', 'Промышленное сердце Мирнастана: шахты, крепости, горные перевалы и северная оборона.'),
    ('Астерион', 500000000.0, 'maps/asterion.jpg', 'Центральная провинция Империи: столица, торговые тракты, порты и плодородные равнины.'),
    ('Мирноуль', 20000000.0, 'maps/mirnoul.jpg', 'Житница и лесной край: поля, реки, озёра, лечебные травы и южные дороги.'),
]
DEFAULT_USERS = [
    ('emperor', 'emperor'),
    ('king_nerdia', 'king'),
    ('king_asterion', 'king'),
    ('king_mirnoul', 'king'),
    ('graf_nerdia_1', 'graf'),
    ('graf_asterion_1', 'graf'),
    ('graf_mirnoul_1', 'graf'),
]
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


def get_current_time():
    if APP_TIMEZONE:
        try:
            return datetime.now(ZoneInfo(APP_TIMEZONE))
        except ZoneInfoNotFoundError:
            pass
    return datetime.now()


def get_table_columns(db, table_name):
    return [row[1] for row in db.execute(f'PRAGMA table_info({table_name})')]


def ensure_column(db, table_name, column_name, definition):
    columns = get_table_columns(db, table_name)
    if columns and column_name not in columns:
        db.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


def ensure_setting(db, key, value):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if row is None:
        db.execute('INSERT INTO settings (key, value) VALUES (?,?)', (key, str(value)))


def set_setting(db, key, value):
    cur = db.execute('UPDATE settings SET value=? WHERE key=?', (str(value), key))
    if cur.rowcount == 0:
        db.execute('INSERT INTO settings (key, value) VALUES (?,?)', (key, str(value)))


def get_setting_value(db, key, default=''):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if row and row[0] is not None:
        return row[0]
    return default


def get_setting_float(db, key, default=0.0):
    try:
        return float(get_setting_value(db, key, default))
    except (TypeError, ValueError):
        return default


def ensure_runtime_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        role TEXT,
        password_hash TEXT,
        balance REAL DEFAULT 0,
        daily_income REAL DEFAULT 0,
        kingdom_name TEXT DEFAULT '',
        county_name TEXT DEFAULT ''
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS kingdoms (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        budget REAL DEFAULT 0,
        daily_income REAL DEFAULT 0,
        map_image TEXT DEFAULT '',
        map_notes TEXT DEFAULT '',
        tree REAL DEFAULT 0,
        metal REAL DEFAULT 0,
        food REAL DEFAULT 0,
        tree_income REAL DEFAULT 0,
        metal_income REAL DEFAULT 0,
        food_income REAL DEFAULT 0
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS duchies (
        id INTEGER PRIMARY KEY,
        kingdom_id INTEGER,
        kingdom_name TEXT,
        name TEXT,
        budget REAL DEFAULT 0,
        tree REAL DEFAULT 0,
        metal REAL DEFAULT 0,
        food REAL DEFAULT 0,
        tree_income REAL DEFAULT 0,
        metal_income REAL DEFAULT 0,
        food_income REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        key TEXT UNIQUE,
        value TEXT
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        from_user INTEGER,
        to_kingdom INTEGER,
        amount REAL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS reports (
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
    db.execute('''CREATE TABLE IF NOT EXISTS cards (
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
    db.execute('''CREATE TABLE IF NOT EXISTS imperial_council (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        council_income REAL DEFAULT 0,
        note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS counties (
        id INTEGER PRIMARY KEY,
        kingdom_name TEXT,
        name TEXT,
        graf_user_id INTEGER,
        duchy_id INTEGER DEFAULT NULL,
        map_hint TEXT DEFAULT '',
        map_x REAL DEFAULT 50,
        map_y REAL DEFAULT 50,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(kingdom_name, name)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS building_requests (
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


def seed_runtime_defaults(db):
    for name, budget, map_image, map_notes in DEFAULT_KINGDOMS:
        db.execute('INSERT OR IGNORE INTO kingdoms (name, budget, map_image, map_notes) VALUES (?,?,?,?)', (name, budget, map_image, map_notes))
        db.execute(
            '''UPDATE kingdoms
               SET map_image = COALESCE(NULLIF(map_image, ''), ?),
                   map_notes = COALESCE(NULLIF(map_notes, ''), ?)
               WHERE name=?''',
            (map_image, map_notes, name),
        )
    ensure_setting(db, 'treasury', str(DEFAULT_TREASURY))
    ensure_setting(db, DAILY_INCOME_LAST_DATE_KEY, '')
    ensure_setting(db, 'empire_map_image', 'maps/mirnastan.jpg')
    ensure_setting(db, 'empire_map_notes', 'Общая карта империи с тремя провинциями: Астерион, Нердия и Мирноуль.')

    for username, role in DEFAULT_USERS:
        existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing is None:
            db.execute(
                'INSERT INTO users (username, role, password_hash, kingdom_name) VALUES (?,?,?,?)',
                (username, role, generate_password_hash(f'{username}_pass'), default_kingdom_for_username(username) or ''),
            )
        else:
            kingdom_name = default_kingdom_for_username(username)
            if kingdom_name:
                db.execute(
                    "UPDATE users SET kingdom_name = COALESCE(NULLIF(kingdom_name, ''), ?) WHERE username=?",
                    (kingdom_name, username),
                )
    for kingdom_name, county_name, username, map_hint, map_x, map_y in DEFAULT_COUNTIES:
        existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing is None:
            db.execute(
                'INSERT INTO users (username, role, password_hash, kingdom_name, county_name) VALUES (?,?,?,?,?)',
                (username, 'graf', generate_password_hash(f'{username}_pass'), kingdom_name, county_name),
            )
            existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        else:
            db.execute(
                "UPDATE users SET role='graf', kingdom_name=COALESCE(NULLIF(kingdom_name, ''), ?), county_name=COALESCE(NULLIF(county_name, ''), ?) WHERE username=?",
                (kingdom_name, county_name, username),
            )
        db.execute(
            'INSERT OR IGNORE INTO counties (kingdom_name, name, graf_user_id, map_hint, map_x, map_y) VALUES (?,?,?,?,?,?)',
            (kingdom_name, county_name, existing['id'], map_hint, map_x, map_y),
        )
        db.execute(
            '''UPDATE counties
               SET graf_user_id=COALESCE(graf_user_id, ?),
                   map_hint=COALESCE(NULLIF(map_hint, ''), ?),
                   map_x=COALESCE(map_x, ?),
                   map_y=COALESCE(map_y, ?)
               WHERE kingdom_name=? AND name=?''',
            (existing['id'], map_hint, map_x, map_y, kingdom_name, county_name),
        )


def ensure_runtime_schema(db):
    ensure_runtime_tables(db)
    ensure_column(db, 'users', 'balance', 'REAL DEFAULT 0')
    ensure_column(db, 'users', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(db, 'users', 'kingdom_name', "TEXT DEFAULT ''")
    ensure_column(db, 'users', 'county_name', "TEXT DEFAULT ''")
    ensure_column(db, 'kingdoms', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'map_image', "TEXT DEFAULT ''")
    ensure_column(db, 'kingdoms', 'map_notes', "TEXT DEFAULT ''")
    ensure_column(db, 'reports', 'report_type', 'TEXT')
    ensure_column(db, 'reports', 'title', 'TEXT')
    ensure_column(db, 'reports', 'author_name', 'TEXT')
    ensure_column(db, 'reports', 'recipient_name', 'TEXT')
    ensure_column(db, 'reports', 'nickname', 'TEXT')
    ensure_column(db, 'reports', 'posted', 'INTEGER DEFAULT 0')
    ensure_column(db, 'cards', 'description', "TEXT DEFAULT ''")
    ensure_column(db, 'cards', 'card_type', "TEXT DEFAULT 'action'")
    ensure_column(db, 'cards', 'rarity', "TEXT DEFAULT 'common'")
    ensure_column(db, 'cards', 'effect', "TEXT DEFAULT ''")
    ensure_column(db, 'cards', 'owner_id', 'INTEGER')
    ensure_column(db, 'cards', 'for_trade', 'INTEGER DEFAULT 0')
    ensure_column(db, 'imperial_council', 'council_income', 'REAL DEFAULT 0')
    ensure_column(db, 'imperial_council', 'note', "TEXT DEFAULT ''")
    ensure_column(db, 'counties', 'graf_user_id', 'INTEGER')
    ensure_column(db, 'counties', 'duchy_id', 'INTEGER DEFAULT NULL')
    ensure_column(db, 'kingdoms', 'tree', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'metal', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'food', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'tree_income', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'metal_income', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'food_income', 'REAL DEFAULT 0')

    # building_requests columns (for existing DBs)
    for col, defn in [
        ('kingdom_id', 'INTEGER'),
        ('kingdom_name', 'TEXT'),
        ('county_id', 'INTEGER'),
        ('county_name', 'TEXT'),
        ('requested_by_user_id', 'INTEGER'),
        ('requested_by_username', 'TEXT'),
        ('requested_by_role', 'TEXT'),
        ('item_name', 'TEXT'),
        ('requested_tree_cost', 'REAL DEFAULT 0'),
        ('requested_metal_cost', 'REAL DEFAULT 0'),
        ('requested_food_cost', 'REAL DEFAULT 0'),
        ('requested_kingdom_cash_cost', 'REAL DEFAULT 0'),
        ('treasury_cash_covered', 'REAL DEFAULT 0'),
        ('kingdom_cash_cost', 'REAL DEFAULT 0'),
        ('proposed_tree_income', 'REAL DEFAULT 0'),
        ('proposed_metal_income', 'REAL DEFAULT 0'),
        ('proposed_food_income', 'REAL DEFAULT 0'),
        ('status', "TEXT DEFAULT 'submitted'"),
        ('reason', "TEXT DEFAULT ''"),
        ('approved_by_user_id', 'INTEGER'),
        ('approved_by_username', 'TEXT'),
        ('approved_at', 'TIMESTAMP'),
    ]:
        ensure_column(db, 'building_requests', col, defn)

    ensure_column(db, 'counties', 'map_hint', "TEXT DEFAULT ''")
    ensure_column(db, 'counties', 'map_x', 'REAL DEFAULT 50')
    ensure_column(db, 'counties', 'map_y', 'REAL DEFAULT 50')

    # Auto-create duchies for each existing kingdom (if DB pre-dates duchies)
    # and attach counties to duchy_id when it's missing.
    try:
        duchy_count = db.execute('SELECT COUNT(*) FROM duchies').fetchone()[0]
    except sqlite3.OperationalError:
        duchy_count = 0

    if duchy_count == 0:
        kingdoms = db.execute('SELECT id, name FROM kingdoms').fetchall()
        for k in kingdoms:
            db.execute(
                'INSERT INTO duchies (kingdom_id, kingdom_name, name, budget) VALUES (?,?,?,0)',
                (k['id'], k['name'], f'Герцогство {k["name"]}'),
            )

    db.execute(
        '''
        UPDATE counties
        SET duchy_id = (
            SELECT d.id
            FROM duchies d
            WHERE d.kingdom_id = (
                SELECT id FROM kingdoms WHERE name = counties.kingdom_name
            )
            ORDER BY d.id
            LIMIT 1
        )
        WHERE duchy_id IS NULL
        '''
    )

    seed_runtime_defaults(db)
    db.commit()


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    ensure_runtime_schema(db)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def get_user(username):
    return query_db('SELECT * FROM users WHERE username=?', (username,), one=True)


def role_can_manage_money(role):
    return (role or '').lower() in {'emperor', 'king', 'graf', 'peasant', 'citizen', 'merchant', 'artisan'}


def role_is_authority(role):
    return (role or '').lower() in AUTHORITY_ROLES


def get_user_kingdom_name(user):
    username = (user or {}).get('username', '')
    explicit_kingdom = (user or {}).get('kingdom_name') or ''
    if explicit_kingdom:
        return explicit_kingdom
    return default_kingdom_for_username(username)


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


def user_can_manage_income_for_user(manager, target):
    manager_role = (manager or {}).get('role', '').lower()
    if manager_role == 'emperor':
        return target is not None and target['role'] != 'emperor'
    if manager_role != 'king' or target is None:
        return False
    if target['role'] in ('emperor', 'king'):
        return False
    manager_kingdom = get_user_kingdom_name(manager)
    target_kingdom = target['kingdom_name'] or default_kingdom_for_username(target['username'])
    return bool(manager_kingdom and target_kingdom == manager_kingdom)


def get_council_members(db):
    return db.execute(
        '''SELECT c.id, c.user_id, c.council_income, c.note, c.created_at,
                  u.username, u.role, u.balance, u.kingdom_name
           FROM imperial_council c
           JOIN users u ON u.id=c.user_id
           ORDER BY c.created_at DESC'''
    ).fetchall()


def get_counties_for_user(db, user):
    if (user or {}).get('role') == 'emperor':
        return db.execute(
            '''SELECT c.*, u.username AS graf_username, u.balance AS graf_balance,
                      u.daily_income AS graf_daily_income
               FROM counties c
               LEFT JOIN users u ON u.id=c.graf_user_id
               ORDER BY c.kingdom_name, c.name'''
        ).fetchall()
    kingdom_name = get_user_kingdom_name(user)
    return db.execute(
        '''SELECT c.*, u.username AS graf_username, u.balance AS graf_balance,
                  u.daily_income AS graf_daily_income
           FROM counties c
           LEFT JOIN users u ON u.id=c.graf_user_id
           WHERE c.kingdom_name=?
           ORDER BY c.name''',
        (kingdom_name,),
    ).fetchall()


def get_county(db, county_id):
    return db.execute(
        '''SELECT c.*, u.username AS graf_username, u.role AS graf_role,
                  u.balance AS graf_balance, u.daily_income AS graf_daily_income
           FROM counties c
           LEFT JOIN users u ON u.id=c.graf_user_id
           WHERE c.id=?''',
        (county_id,),
    ).fetchone()


def user_can_manage_county(user, county):
    if not county:
        return False
    role = (user or {}).get('role', '').lower()
    if role == 'emperor':
        return True
    return role == 'king' and get_user_kingdom_name(user) == county['kingdom_name']


def generate_password(username):
    safe_name = ''.join(ch for ch in username if ch.isalnum())[-8:] or 'graf'
    return f'{safe_name}_{secrets.token_hex(3)}'


def set_user_password(db, user_id, password):
    if not password:
        return False
    target = db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone()
    if not target:
        return False
    db.execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(password), user_id))
    return True


def emperor_can_manage_king_password(manager, target):
    return (manager or {}).get('role') == 'emperor' and target is not None and target['role'] == 'king'


def user_can_manage_kingdom(user, kingdom_id):
    if (user or {}).get('role', '').lower() == 'emperor':
        return True
    kingdom_name = get_user_kingdom_name(user)
    if not kingdom_name:
        return False
    kingdom = query_db('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,), one=True)
    return kingdom is not None and kingdom['name'] == kingdom_name


def get_user_kingdom(db, user):
    kingdom_name = get_user_kingdom_name(user)
    if not kingdom_name:
        return None
    return db.execute('SELECT * FROM kingdoms WHERE name=?', (kingdom_name,)).fetchone()


def get_user_balance(db, username):
    if not username:
        return 0.0
    row = db.execute('SELECT balance FROM users WHERE username=?', (username,)).fetchone()
    if row and row[0] is not None:
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def get_treasury_from_db(db):
    return get_setting_float(db, 'treasury', DEFAULT_TREASURY)


def get_treasury():
    return get_treasury_from_db(get_db())


def parse_money_amount(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return amount


def send_report_to_telegram():
    try:
        import telegram_bot
        telegram_bot.DB = DB_PATH
        telegram_bot.process_pending_reports()
    except Exception as exc:
        print('Telegram send failed:', exc)


def insert_report(db, kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname):
    db.execute(
        'INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
        (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname),
    )


# NOTE: parse_resource_amount is required for resources (Д/М/П).

def parse_resource_amount(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return amount


def apply_resource_transfer_between_kingdoms(
    db,
    from_kingdom_id,
    to_kingdom_id,
    tree_amount,
    metal_amount,
    food_amount,
    acting_user=None,
    description='',
):
    from_kingdom_id = from_kingdom_id
    to_kingdom_id = to_kingdom_id
    if str(from_kingdom_id) == str(to_kingdom_id):
        return False

    tree_amount = parse_resource_amount(tree_amount)
    metal_amount = parse_resource_amount(metal_amount)
    food_amount = parse_resource_amount(food_amount)
    if tree_amount is None or metal_amount is None or food_amount is None:
        return False

    total = tree_amount + metal_amount + food_amount
    if total <= 0:
        return False

    from_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (from_kingdom_id,)).fetchone()
    to_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (to_kingdom_id,)).fetchone()
    if not from_kingdom or not to_kingdom:
        return False

    if float(from_kingdom['tree'] or 0) < tree_amount:
        return False
    if float(from_kingdom['metal'] or 0) < metal_amount:
        return False
    if float(from_kingdom['food'] or 0) < food_amount:
        return False

    acting_user = acting_user or {}
    role = (acting_user.get('role') or '').lower()
    username = acting_user.get('username')

    # Emperor can transfer anything; others only from their own kingdom.
    if role != 'emperor' and username and not user_can_manage_kingdom(acting_user, from_kingdom_id):
        return False

    author_name = 'Император' if role == 'emperor' else (username or 'Игрок')
    nickname = 'Казна Императора' if role == 'emperor' else (username or 'Личный баланс')

    db.execute('UPDATE kingdoms SET tree=tree-? WHERE id=?', (tree_amount, from_kingdom_id))
    db.execute('UPDATE kingdoms SET metal=metal-? WHERE id=?', (metal_amount, from_kingdom_id))
    db.execute('UPDATE kingdoms SET food=food-? WHERE id=?', (food_amount, from_kingdom_id))

    db.execute('UPDATE kingdoms SET tree=tree+? WHERE id=?', (tree_amount, to_kingdom_id))
    db.execute('UPDATE kingdoms SET metal=metal+? WHERE id=?', (metal_amount, to_kingdom_id))
    db.execute('UPDATE kingdoms SET food=food+? WHERE id=?', (food_amount, to_kingdom_id))

    insert_report(
        db,
        to_kingdom_id,
        'Ресурсы: перевод',
        total,
        'Перевод ресурсов',
        f'Передано ресурсы из {from_kingdom["name"]}: дерево={tree_amount}; металл={metal_amount}; продовольствие={food_amount}. Причина: {description or "перераспределение"}',
        author_name,
        to_kingdom['name'],
        nickname,
    )

    db.execute(
        'INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
        (None, to_kingdom_id, total, description or 'Перевод ресурсов между королевствами'),
    )

    return True


def submit_building_request(
    db,
    county_id,
    item_name,
    requested_tree_cost,
    requested_metal_cost,
    requested_food_cost,
    acting_user=None,
    reason='',
    requested_kingdom_cash_cost=0,
):
    county = get_county(db, county_id)
    if not county:
        return False

    item_name = (item_name or '').strip()
    if not item_name:
        return False

    requested_tree_cost = parse_resource_amount(requested_tree_cost)
    requested_metal_cost = parse_resource_amount(requested_metal_cost)
    requested_food_cost = parse_resource_amount(requested_food_cost)
    requested_kingdom_cash_cost = parse_resource_amount(requested_kingdom_cash_cost)

    if None in (requested_tree_cost, requested_metal_cost, requested_food_cost, requested_kingdom_cash_cost):
        return False

    acting_user = acting_user or {}
    role = (acting_user.get('role') or '').lower()
    username = acting_user.get('username')

    # graf: only own counties; king: any in his kingdom; emperor: allow too (optional)
    if role != 'emperor':
        if role == 'graf':
            if float(county['graf_user_id'] or 0) == 0:
                return False
            if county['graf_user_id'] != acting_user.get('id') and username != (county.get('graf_username') if hasattr(county, 'get') else None):
                return False
        else:
            if role != 'king' or not user_can_manage_county(acting_user, county):
                return False

    kingdom = db.execute('SELECT * FROM kingdoms WHERE name=?', (county['kingdom_name'],)).fetchone()
    if not kingdom:
        return False

    # resources are set by emperor on approve, so no check needed at submit time
    # only validate that requested_kingdom_cash_cost is a valid number
    if requested_kingdom_cash_cost < 0:
        return False

    db.execute(
        '''INSERT INTO building_requests (
            kingdom_id, kingdom_name, county_id, county_name,
            requested_by_user_id, requested_by_username, requested_by_role,
            item_name,
            requested_tree_cost, requested_metal_cost, requested_food_cost,
            requested_kingdom_cash_cost,
            treasury_cash_covered,
            kingdom_cash_cost,
            proposed_tree_income, proposed_metal_income, proposed_food_income,
            status, reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?, ?)''',
        (
            kingdom['id'],
            kingdom['name'],
            county['id'],
            county['name'],
            acting_user.get('id'),
            username,
            role,
            item_name,
            0,  # requested_tree_cost - will be set by emperor on approve
            0,  # requested_metal_cost - will be set by emperor on approve
            0,  # requested_food_cost - will be set by emperor on approve
            requested_kingdom_cash_cost,
            0,  # treasury_cash_covered (will be set on approve)
            0,  # kingdom_cash_cost (will be set on approve)
            0,  # proposed_* income (set on approve)
            0,
            0,
            'submitted',
            reason or '',
        ),
    )

    # telegram: ensure it goes to emperor thread (no kingdom binding)
    insert_report(
        db,
        None,
        'Постройка: заявка',
        0,
        'Заявка на постройку',
        f'Заявлена постройка "{item_name}" на графстве {county["name"]}. Сумма проекта: {requested_kingdom_cash_cost}. Причина: {reason or "-"}',
        'Император' if role == 'emperor' else (username or 'Игрок'),
        'Император',
        'Казна Императора' if role == 'emperor' else (username or 'Личный баланс'),
    )

    return True


def approve_building_request(
    db,
    request_id,
    emperor_username,
    treasury_cash_covered,
    kingdom_cash_cost,
    proposed_tree_income,
    proposed_metal_income,
    proposed_food_income,
    reason='',
    requested_tree_cost=0,
    requested_metal_cost=0,
    requested_food_cost=0,
):
    req = db.execute('SELECT * FROM building_requests WHERE id=?', (request_id,)).fetchone()
    if not req:
        return False
    if req['status'] != 'submitted':
        return False

    treasury_cash_covered = parse_money_amount(treasury_cash_covered)
    kingdom_cash_cost = parse_money_amount(kingdom_cash_cost)
    if treasury_cash_covered is None or kingdom_cash_cost is None:
        return False
    if treasury_cash_covered < 0 or kingdom_cash_cost < 0:
        return False

    # Parse resource costs set by emperor
    requested_tree_cost = parse_resource_amount(requested_tree_cost)
    requested_metal_cost = parse_resource_amount(requested_metal_cost)
    requested_food_cost = parse_resource_amount(requested_food_cost)
    if None in (requested_tree_cost, requested_metal_cost, requested_food_cost):
        return False

    kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (req['kingdom_id'],)).fetchone()
    if not kingdom:
        return False

    # re-validate treasury budget coverage
    treasury_cover = float(treasury_cash_covered)
    if get_treasury_from_db(db) < treasury_cover:
        return False

    kingdom_cost = float(kingdom_cash_cost)
    if float(kingdom['budget'] or 0) < kingdom_cost:
        return False

    # re-validate resource availability (resources are always taken from kingdom pool)
    if float(kingdom['tree'] or 0) < requested_tree_cost:
        return False
    if float(kingdom['metal'] or 0) < requested_metal_cost:
        return False
    if float(kingdom['food'] or 0) < requested_food_cost:
        return False

    proposed_tree_income = parse_resource_amount(proposed_tree_income)
    proposed_metal_income = parse_resource_amount(proposed_metal_income)
    proposed_food_income = parse_resource_amount(proposed_food_income)
    if None in (proposed_tree_income, proposed_metal_income, proposed_food_income):
        return False

    # persist final costs into request (for transparency) - but DON'T deduct yet
    # resources will be deducted when requester confirms
    db.execute(
        '''UPDATE building_requests
           SET requested_tree_cost=?,
               requested_metal_cost=?,
               requested_food_cost=?,
               treasury_cash_covered=?,
               kingdom_cash_cost=?,
               proposed_tree_income=?,
               proposed_metal_income=?,
               proposed_food_income=?,
               status='emperor_approved',
               approved_by_user_id=NULL,
               approved_by_username=?,
               approved_at=CURRENT_TIMESTAMP,
               reason=?,
               emperor_approved=1
           WHERE id=?''',
        (requested_tree_cost, requested_metal_cost, requested_food_cost, treasury_cover, kingdom_cost, 
         proposed_tree_income, proposed_metal_income, proposed_food_income,
         emperor_username, reason or '', request_id),
    )

    insert_report(
        db,
        None,
        'Постройка: одобрено императором',
        kingdom_cost + treasury_cover,
        'Одобрение постройки императором',
        f'Император одобрил постройку "{req["item_name"]}" на графстве {req["county_name"]}. Требуется подтверждение от заявителя. Планируемые расходы: деньги королевства={kingdom_cost}, казна={treasury_cover}; ресурсы: дерево={requested_tree_cost}, металл={requested_metal_cost}, еда={requested_food_cost}. Доход от постройки: дерево+{proposed_tree_income}, металл+{proposed_metal_income}, еда+{proposed_food_income}. Причина: {reason or "-"}',
        'Император',
        'Император',
        'Казна Императора',
    )

    return True


def reject_building_request(
    db,
    request_id,
    emperor_username,
    reason='',
):
    req = db.execute('SELECT * FROM building_requests WHERE id=?', (request_id,)).fetchone()
    if not req:
        return False
    # Allow rejecting both submitted and emperor_approved requests
    if req['status'] not in ('submitted', 'emperor_approved'):
        return False

    db.execute(
        '''UPDATE building_requests
           SET status='rejected',
               approved_by_user_id=NULL,
               approved_by_username=?,
               approved_at=CURRENT_TIMESTAMP,
               reason=?
           WHERE id=?''',
        (emperor_username, reason or '', request_id),
    )

    insert_report(
        db,
        None,
        'Постройка: отклонено',
        0,
        'Отклонение постройки',
        f'Император отклонил постройку "{req["item_name"]}" на графстве {req["county_name"]}. Причина: {reason or "-"}',
        'Император',
        'Император',
        'Казна Императора',
    )

    return True


def confirm_building_request(
    db,
    request_id,
    requester_username,
):
    """Requester confirms the building after emperor approval.
    This deducts resources and starts construction (1 hour).
    """
    req = db.execute('SELECT * FROM building_requests WHERE id=?', (request_id,)).fetchone()
    if not req:
        return False
    if req['status'] != 'emperor_approved':
        return False
    
    # Verify the requester is the one who submitted
    if req['requested_by_username'] != requester_username:
        return False
    
    kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (req['kingdom_id'],)).fetchone()
    if not kingdom:
        return False
    
    treasury_cover = float(req['treasury_cash_covered'] or 0)
    kingdom_cost = float(req['kingdom_cash_cost'] or 0)
    requested_tree_cost = float(req['requested_tree_cost'] or 0)
    requested_metal_cost = float(req['requested_metal_cost'] or 0)
    requested_food_cost = float(req['requested_food_cost'] or 0)
    
    proposed_tree_income = float(req['proposed_tree_income'] or 0)
    proposed_metal_income = float(req['proposed_metal_income'] or 0)
    proposed_food_income = float(req['proposed_food_income'] or 0)
    
    # Re-validate resources availability
    if float(kingdom['tree'] or 0) < requested_tree_cost:
        return False
    if float(kingdom['metal'] or 0) < requested_metal_cost:
        return False
    if float(kingdom['food'] or 0) < requested_food_cost:
        return False
    if float(kingdom['budget'] or 0) < kingdom_cost:
        return False
    
    # Check treasury again
    if get_treasury_from_db(db) < treasury_cover:
        return False
    
    requester_role = (req['requested_by_role'] or '').lower()
    # 80/20 for graf, 100% for king
    if requester_role == 'graf':
        duchy_share = 0.8
        kingdom_share = 0.2
    elif requester_role == 'king':
        duchy_share = 0.0
        kingdom_share = 1.0
    else:
        duchy_share = 0.0
        kingdom_share = 1.0

    # resolve duchy for the county (where building is located)
    county = get_county(db, req['county_id'])
    if not county:
        return False

    duchy_id = county['duchy_id']
    if duchy_id is None:
        duchy_share = 0.0
        kingdom_share = 1.0

    duchy_tree_income = proposed_tree_income * duchy_share
    duchy_metal_income = proposed_metal_income * duchy_share
    duchy_food_income = proposed_food_income * duchy_share

    kingdom_tree_income = proposed_tree_income * kingdom_share
    kingdom_metal_income = proposed_metal_income * kingdom_share
    kingdom_food_income = proposed_food_income * kingdom_share
    
    from datetime import timedelta
    now = datetime.now()
    finished_at = now + timedelta(hours=1)
    
    # Deduct money and resources
    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (treasury_cover,))
    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (kingdom_cost, req['kingdom_id']))
    db.execute('UPDATE kingdoms SET tree = tree - ? WHERE id=?', (requested_tree_cost, req['kingdom_id']))
    db.execute('UPDATE kingdoms SET metal = metal - ? WHERE id=?', (requested_metal_cost, req['kingdom_id']))
    db.execute('UPDATE kingdoms SET food = food - ? WHERE id=?', (requested_food_cost, req['kingdom_id']))
    
    # Set up income to be applied when construction finishes
    if duchy_share > 0 and duchy_id:
        db.execute('UPDATE duchies SET tree_income = COALESCE(tree_income,0) + ? WHERE id=?', (duchy_tree_income, duchy_id))
        db.execute('UPDATE duchies SET metal_income = COALESCE(metal_income,0) + ? WHERE id=?', (duchy_metal_income, duchy_id))
        db.execute('UPDATE duchies SET food_income = COALESCE(food_income,0) + ? WHERE id=?', (duchy_food_income, duchy_id))

    if kingdom_share > 0:
        db.execute('UPDATE kingdoms SET tree_income = COALESCE(tree_income,0) + ? WHERE id=?', (kingdom_tree_income, req['kingdom_id']))
        db.execute('UPDATE kingdoms SET metal_income = COALESCE(metal_income,0) + ? WHERE id=?', (kingdom_metal_income, req['kingdom_id']))
        db.execute('UPDATE kingdoms SET food_income = COALESCE(food_income,0) + ? WHERE id=?', (kingdom_food_income, req['kingdom_id']))
    
    # Update request status
    db.execute(
        '''UPDATE building_requests
           SET status='building',
               requester_confirmed=1,
               construction_started_at=CURRENT_TIMESTAMP,
               construction_finished_at=?
           WHERE id=?''',
        (finished_at.strftime('%Y-%m-%d %H:%M:%S'), request_id),
    )
    
    insert_report(
        db,
        None,
        'Постройка: началось строительство',
        kingdom_cost + treasury_cover,
        'Строительство началось',
        f'Заявитель подтвердил постройку "{req["item_name"]}" на графстве {req["county_name"]}. Строительство начато и завершится через 1 час. Ресурсы списаны.',
        requester_username or 'Заявитель',
        'Император',
        'Казна Императора',
    )
    
    return True


def apply_people_expense(db, amount, description='', acting_user=None):

    amount = float(amount)
    if amount <= 0:
        return False
    acting_user = acting_user or {}
    role = acting_user.get('role', '').lower()
    username = acting_user.get('username')
    report_kingdom_id = None

    if role == 'emperor' or not username:
        if get_treasury_from_db(db) < amount:
            return False
        db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
        from_user_id = None
        author_name = 'Император'
        nickname = 'Казна Императора'
    elif role in AUTHORITY_ROLES:
        kingdom = get_user_kingdom(db, acting_user)
        if not kingdom or float(kingdom['budget'] or 0) < amount:
            return False
        db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, kingdom['id']))
        from_user_id = None
        report_kingdom_id = kingdom['id']
        role_title = 'Король' if role == 'king' else 'Граф'
        author_name = f'{role_title} {kingdom["name"]}'
        nickname = f'Казна {kingdom["name"]}'
    else:
        if get_user_balance(db, username) < amount:
            return False
        db.execute('UPDATE users SET balance = balance - ? WHERE username=?', (amount, username))
        user_row = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        from_user_id = user_row[0] if user_row else None
        author_name = username or 'Игрок'
        nickname = username or 'Личный баланс'

    insert_report(
        db,
        report_kingdom_id,
        'Расход на народ',
        -amount,
        'Трата на народ',
        f'Средства направлены на нужды населения | {description or "обеспечение благосостояния"}',
        author_name,
        'Народ',
        nickname,
    )
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (from_user_id, report_kingdom_id, -amount, description or 'Расход на народ'))
    return True


def apply_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, amount, description='', acting_user=None):
    amount = float(amount)
    if amount <= 0 or str(from_kingdom_id) == str(to_kingdom_id):
        return False
    from_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (from_kingdom_id,)).fetchone()
    to_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (to_kingdom_id,)).fetchone()
    if not from_kingdom or not to_kingdom or float(from_kingdom['budget'] or 0) < amount:
        return False

    acting_user = acting_user or {}
    role = acting_user.get('role', '').lower()
    username = acting_user.get('username')
    if role != 'emperor' and username and not user_can_manage_kingdom(acting_user, from_kingdom_id):
        return False

    author_name = 'Император' if role == 'emperor' else (username or 'Игрок')
    nickname = 'Казна Императора' if role == 'emperor' else (username or 'Личный баланс')
    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, from_kingdom_id))
    db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, to_kingdom_id))
    insert_report(
        db,
        to_kingdom_id,
        'Перевод',
        amount,
        'Перевод между королевствами',
        f'Переведено {amount} из {from_kingdom["name"]} | {description or "перераспределение ресурсов"}',
        author_name,
        to_kingdom['name'],
        nickname,
    )
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, to_kingdom_id, amount, description or 'Перевод между королевствами'))
    return True


def get_report_defaults_for_user(user):
    kingdom_name = get_user_kingdom_name(user)
    role = (user or {}).get('role', '').lower()
    if not kingdom_name:
        return {'kingdom': None, 'author_name': None, 'recipient_name': None, 'nickname': None}
    if role == 'king':
        return {'kingdom': kingdom_name, 'author_name': f'Король {kingdom_name}', 'recipient_name': 'Император', 'nickname': f'Король {kingdom_name}'}
    if role == 'graf':
        return {'kingdom': kingdom_name, 'author_name': f'Граф {kingdom_name}', 'recipient_name': f'Король {kingdom_name}', 'nickname': f'Граф {kingdom_name}'}
    return {'kingdom': kingdom_name, 'author_name': user.get('username'), 'recipient_name': 'Совет', 'nickname': user.get('username')}


def set_user_daily_income(db, user_id, amount):
    amount = parse_money_amount(amount)
    if amount is None:
        return False
    user = db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        return False
    db.execute('UPDATE users SET daily_income=? WHERE id=?', (amount, user_id))
    return True


def set_kingdom_daily_income(db, kingdom_id, amount):
    amount = parse_money_amount(amount)
    if amount is None:
        return False
    kingdom = db.execute('SELECT id FROM kingdoms WHERE id=?', (kingdom_id,)).fetchone()
    if not kingdom:
        return False
    db.execute('UPDATE kingdoms SET daily_income=? WHERE id=?', (amount, kingdom_id))
    return True


def create_daily_income_assignment_report(db, amount, recipient_name, target_kind, kingdom_id=None):
    action = 'отключен' if float(amount) == 0 else 'назначен'
    insert_report(
        db,
        kingdom_id,
        'Назначение дохода',
        float(amount),
        'Настройка ежедневного дохода',
        f'Ежедневный доход {action}: {target_kind} {recipient_name} | сумма {float(amount)} каждый день в 00:01',
        'Император',
        recipient_name,
        'Казна Императора',
    )


def get_configured_income_recipients(db):
    users = db.execute("SELECT id, username, role, daily_income FROM users WHERE role != 'emperor' AND COALESCE(daily_income, 0) > 0").fetchall()
    kingdoms = db.execute('SELECT id, name, daily_income FROM kingdoms WHERE COALESCE(daily_income, 0) > 0').fetchall()
    try:
        council = db.execute(
            '''SELECT c.user_id AS id, u.username, u.role, c.council_income
               FROM imperial_council c
               JOIN users u ON u.id=c.user_id
               WHERE COALESCE(c.council_income, 0) > 0'''
        ).fetchall()
    except sqlite3.OperationalError:
        council = []
    return users, kingdoms, council


def apply_configured_daily_income(db, run_date, description=''):
    if get_setting_value(db, DAILY_INCOME_LAST_DATE_KEY, '') == run_date:
        return False
    users, kingdoms, council = get_configured_income_recipients(db)
    player_total = sum(float(user['daily_income'] or 0) for user in users if not role_is_authority(user['role']))
    authority_total = sum(float(user['daily_income'] or 0) for user in users if role_is_authority(user['role']))
    kingdom_total = sum(float(kingdom['daily_income'] or 0) for kingdom in kingdoms)
    council_total = sum(float(member['council_income'] or 0) for member in council)
    total = player_total + authority_total + kingdom_total + council_total
    if total <= 0 or get_treasury_from_db(db) < total:
        return False

    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (total,))
    for user in users:
        db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (float(user['daily_income']), user['id']))
    for member in council:
        db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (float(member['council_income']), member['id']))
    for kingdom in kingdoms:
        amount = float(kingdom['daily_income'])
        db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, kingdom['id']))
        db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, kingdom['id'], amount, description or 'Ежедневный доход королевству'))

    insert_report(
        db,
        None,
        'Ежедневный доход',
        total,
        'Ежедневный доход',
        f'Игрокам: {player_total}; Власти: {authority_total}; Королевствам: {kingdom_total}; Совету: {council_total} | {description or "автоматическая выплата в 00:01"}',
        'Император',
        'Игроки, власть и королевства',
        'Казна Императора',
    )
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, None, total, description or 'Ежедневный доход'))
    set_setting(db, DAILY_INCOME_LAST_DATE_KEY, run_date)
    return True


DAILY_RESOURCE_INCOME_LAST_DATE_KEY = 'daily_resource_income_last_date'


def apply_configured_daily_resource_income(db, run_date, description=''):
    if get_setting_value(db, DAILY_RESOURCE_INCOME_LAST_DATE_KEY, '') == run_date:
        return False

    duchies = db.execute(
        '''SELECT
               id,
               kingdom_id,
               kingdom_name,
               name,
               COALESCE(tree_income,0) AS tree_income,
               COALESCE(metal_income,0) AS metal_income,
               COALESCE(food_income,0) AS food_income
           FROM duchies'''
    ).fetchall()

    total_tree = 0.0
    total_metal = 0.0
    total_food = 0.0

    paid_any = False
    for d in duchies:
        tree_add = float(d['tree_income'] or 0)
        metal_add = float(d['metal_income'] or 0)
        food_add = float(d['food_income'] or 0)
        if tree_add <= 0 and metal_add <= 0 and food_add <= 0:
            continue

        paid_any = True
        total_tree += tree_add
        total_metal += metal_add
        total_food += food_add

        db.execute(
            '''UPDATE duchies
               SET tree = COALESCE(tree,0) + ?,
                   metal = COALESCE(metal,0) + ?,
                   food = COALESCE(food,0) + ?
               WHERE id=?''',
            (tree_add, metal_add, food_add, d['id']),
        )

        # для совместимости используем transactions.to_kingdom = kingdom_id
        db.execute(
            'INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
            (None, d['kingdom_id'], tree_add + metal_add + food_add, description or 'Ежедневный доход ресурсам'),
        )

    if not paid_any:
        set_setting(db, DAILY_RESOURCE_INCOME_LAST_DATE_KEY, run_date)
        return False

    insert_report(
        db,
        None,
        'Ежедневный доход ресурсов',
        0,
        'Ежедневный доход ресурсов',
        f'Дерево: {total_tree}; Металл: {total_metal}; Продовольствие: {total_food} | {description or "автоматическая выдача"}',
        'Император',
        'Герцогства',
        'Казна Императора',
    )
    set_setting(db, DAILY_RESOURCE_INCOME_LAST_DATE_KEY, run_date)
    return True



def is_daily_income_time(now):
    return now.hour == DAILY_INCOME_HOUR and now.minute == DAILY_INCOME_MINUTE



def distribute_daily_income(now=None):
    now = now or get_current_time()
    if not is_daily_income_time(now):
        return False
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        ensure_runtime_schema(db)
        paid_money = apply_configured_daily_income(db, now.date().isoformat(), 'автоматическая выплата в 00:01')
        paid_resources = apply_configured_daily_resource_income(db, now.date().isoformat(), 'автоматическая выдача ресурсов в 00:01')
        if paid_money or paid_resources:
            db.commit()
            send_report_to_telegram()
        return paid_money or paid_resources
    finally:
        db.close()



def run_daily_income_loop():
    while True:
        try:
            distribute_daily_income()
        except Exception as exc:
            print('Daily income loop error:', exc)
        time.sleep(60)


threading.Thread(target=run_daily_income_loop, daemon=True).start()


def allowed_map_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MAP_EXTENSIONS


def save_map_upload(file_storage, prefix):
    if not file_storage or not file_storage.filename or not allowed_map_file(file_storage.filename):
        return None
    os.makedirs(MAP_UPLOAD_FOLDER, exist_ok=True)
    ext = secure_filename(file_storage.filename).rsplit('.', 1)[-1].lower()
    filename = f'{secure_filename(prefix)}-{int(time.time())}.{ext}'
    file_storage.save(os.path.join(MAP_UPLOAD_FOLDER, filename))
    return f'maps/{filename}'


def get_empire_map(db):
    return {
        'image': get_setting_value(db, 'empire_map_image', 'maps/mirnastan.jpg'),
        'title': 'Империя Мирнастан',
        'notes': get_setting_value(db, 'empire_map_notes', 'Общая карта империи с тремя провинциями: Астерион, Нердия и Мирноуль.'),
    }


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'peasant')
        kingdom_name = request.form.get('kingdom_name', '')
        if not username or not password:
            flash('Введите логин и пароль')
            return redirect(url_for('register'))
        if get_user(username):
            flash('Пользователь с таким логином уже существует')
            return redirect(url_for('register'))
        db = get_db()
        db.execute(
            'INSERT INTO users (username, role, password_hash, kingdom_name) VALUES (?,?,?,?)',
            (username, role, generate_password_hash(password), kingdom_name),
        )
        db.commit()
        flash('Регистрация выполнена. Теперь войдите в систему.')
        return redirect(url_for('login'))
    roles = [('peasant', 'Крестьянин'), ('citizen', 'Житель'), ('merchant', 'Торговец'), ('artisan', 'Ремесленник')]
    kingdoms = query_db('SELECT name FROM kingdoms ORDER BY name')
    return render_template('register.html', roles=roles, kingdoms=kingdoms)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = {
                'username': user['username'],
                'role': user['role'],
                'balance': user['balance'] or 0,
                'kingdom_name': user['kingdom_name'] or default_kingdom_for_username(user['username']) or '',
            }
            return redirect(url_for('dashboard'))
        flash('Неверные учётные данные')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r LEFT JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC LIMIT 10')
    return render_template('dashboard.html', kingdoms=kingdoms, reports=reports, treasury=get_treasury())


@app.route('/allocate', methods=['POST'])
@login_required
def allocate():
    user = session['user']
    if user['role'] != 'emperor':
        flash('Только император может выделять бюджет')
        return redirect(url_for('dashboard'))
    amount = float(request.form.get('amount', 0) or 0)
    kingdom_id = request.form.get('kingdom_id')
    desc = request.form.get('description', '')
    db = get_db()
    kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,)).fetchone()
    if not kingdom or amount <= 0 or get_treasury_from_db(db) < amount:
        flash('Невозможно выделить средства')
        return redirect(url_for('dashboard'))
    db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, kingdom_id))
    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, kingdom_id, amount, desc))
    insert_report(db, kingdom_id, 'Финансы', amount, 'Выделение бюджета', f'Выделено {amount} | {desc}', 'Император', kingdom['name'], 'Казна Императора')
    db.commit()
    send_report_to_telegram()
    flash('Средства выделены')
    return redirect(url_for('dashboard'))


@app.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    user = session['user']
    if user['role'] != 'emperor':
        flash('Только император может списывать бюджет')
        return redirect(url_for('dashboard'))
    amount = float(request.form.get('amount', 0) or 0)
    kingdom_id = request.form.get('kingdom_id')
    desc = request.form.get('description', '')
    db = get_db()
    kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,)).fetchone()
    if not kingdom or amount <= 0 or float(kingdom['budget'] or 0) < amount:
        flash('Недостаточно средств для списания')
        return redirect(url_for('dashboard'))
    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, kingdom_id))
    db.execute("UPDATE settings SET value = CAST(value AS REAL) + ? WHERE key='treasury'", (amount,))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, kingdom_id, -amount, desc))
    insert_report(db, kingdom_id, 'Финансы', -amount, 'Списание бюджета', f'Списано {amount} | {desc}', 'Император', kingdom['name'], 'Казна Императора')
    db.commit()
    send_report_to_telegram()
    flash('Средства списаны')
    return redirect(url_for('dashboard'))


@app.route('/update_treasury', methods=['POST'])
@login_required
def update_treasury():
    if session['user']['role'] != 'emperor':
        flash('Только император может менять казну')
        return redirect(url_for('dashboard'))
    amount = parse_money_amount(request.form.get('amount', 0))
    if amount is None:
        flash('Неверная сумма')
        return redirect(url_for('dashboard'))
    db = get_db()
    set_setting(db, 'treasury', amount)
    db.commit()
    flash('Казна обновлена')
    return redirect(url_for('dashboard'))


@app.route('/people_expense', methods=['POST'])
@login_required
def people_expense():
    user = session['user']
    if not role_can_manage_money(user['role']):
        flash('У вас нет доступа к финансовым операциям')
        return redirect(url_for('dashboard'))
    db = get_db()
    if apply_people_expense(db, request.form.get('amount', 0), request.form.get('description', ''), acting_user=user):
        db.commit()
        session['user']['balance'] = get_user_balance(db, user['username'])
        send_report_to_telegram()
        flash('Средства направлены на народ')
    else:
        flash('Недостаточно средств')
    return redirect(url_for('dashboard'))


@app.route('/transfer_between_kingdoms', methods=['POST'])
@login_required
def transfer_between_kingdoms():
    user = session['user']
    if not role_can_manage_money(user['role']):
        flash('У вас нет доступа к финансовым операциям')
        return redirect(url_for('dashboard'))
    if user['role'] != 'emperor' and not user_can_manage_kingdom(user, request.form.get('from_kingdom_id')):
        flash('Вы можете переводить средства только из своего королевства')
        return redirect(url_for('dashboard'))
    db = get_db()
    if apply_transfer_between_kingdoms(db, request.form.get('from_kingdom_id'), request.form.get('to_kingdom_id'), request.form.get('amount', 0), request.form.get('description', ''), acting_user=user):
        db.commit()
        send_report_to_telegram()
        flash('Перевод выполнен')
    else:
        flash('Невозможно выполнить перевод')
    return redirect(url_for('dashboard'))


@app.route('/income')
@login_required
def income():
    user = session['user']
    if user['role'] not in ('emperor', 'king'):
        flash('Только император и короли могут управлять доходами')
        return redirect(url_for('dashboard'))
    if user['role'] == 'emperor':
        player_users = query_db("SELECT id, username, role, balance, daily_income, kingdom_name, county_name FROM users WHERE role NOT IN ('emperor','king','graf') ORDER BY username")
        authority_users = query_db("SELECT id, username, role, balance, daily_income, kingdom_name, county_name FROM users WHERE role IN ('king','graf') ORDER BY role, username")
        kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    else:
        kingdom_name = get_user_kingdom_name(user)
        player_users = query_db(
            "SELECT id, username, role, balance, daily_income, kingdom_name, county_name FROM users WHERE role NOT IN ('emperor','king','graf') AND kingdom_name=? ORDER BY username",
            (kingdom_name,),
        )
        authority_users = query_db(
            "SELECT id, username, role, balance, daily_income, kingdom_name, county_name FROM users WHERE role='graf' AND kingdom_name=? ORDER BY username",
            (kingdom_name,),
        )
        kingdoms = []
    return render_template('income.html', player_users=player_users, authority_users=authority_users, kingdoms=kingdoms, treasury=get_treasury(), can_manage_kingdoms=user['role'] == 'emperor')


@app.route('/counties')
@login_required
def counties():
    user = session['user']
    if user['role'] not in ('emperor', 'king'):
        flash('Только император и короли могут управлять графствами')
        return redirect(url_for('dashboard'))
    db = get_db()
    managed_counties = get_counties_for_user(db, user)
    king_users = []
    if user['role'] == 'emperor':
        king_users = query_db("SELECT id, username, kingdom_name FROM users WHERE role='king' ORDER BY kingdom_name, username")
    return render_template('counties.html', counties=managed_counties, king_users=king_users)


@app.route('/counties/income', methods=['POST'])
@login_required
def county_income():
    manager = session['user']
    db = get_db()
    county = get_county(db, request.form.get('county_id'))
    if not user_can_manage_county(manager, county):
        flash('Вы не можете управлять этим графством')
        return redirect(url_for('counties'))
    amount = parse_money_amount(request.form.get('amount', 0))
    if amount is None or not county['graf_user_id']:
        flash('Не удалось назначить доход графу')
        return redirect(url_for('counties'))
    set_user_daily_income(db, county['graf_user_id'], amount)
    insert_report(
        db,
        None,
        'Назначение дохода',
        amount,
        'Доход графства',
        f'Графству {county["name"]} назначен доход {amount}',
        manager['username'],
        county['graf_username'] or county['name'],
        county['kingdom_name'],
    )
    db.commit()
    send_report_to_telegram()
    flash('Доход графства обновлён')
    return redirect(url_for('counties'))


@app.route('/counties/password', methods=['POST'])
@login_required
def county_password():
    manager = session['user']
    db = get_db()
    county = get_county(db, request.form.get('county_id'))
    if not user_can_manage_county(manager, county) or not county['graf_user_id']:
        flash('Вы не можете менять пароль этого графа')
        return redirect(url_for('counties'))
    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        new_password = generate_password(county['graf_username'] or county['name'])
    set_user_password(db, county['graf_user_id'], new_password)
    db.commit()
    flash(f'Новый пароль для {county["graf_username"]}: {new_password}')
    return redirect(url_for('counties'))


@app.route('/kings/password', methods=['POST'])
@login_required
def king_password():
    manager = session['user']
    db = get_db()
    target = db.execute('SELECT id, username, role FROM users WHERE id=?', (request.form.get('user_id'),)).fetchone()
    if not emperor_can_manage_king_password(manager, target):
        flash('Только император может менять пароли королей')
        return redirect(url_for('counties'))
    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        new_password = generate_password(target['username'])
    set_user_password(db, target['id'], new_password)
    db.commit()
    flash(f'Новый пароль для {target["username"]}: {new_password}')
    return redirect(url_for('counties'))


@app.route('/daily_income', methods=['POST'])
@login_required
def daily_income():
    manager = session['user']
    if manager['role'] not in ('emperor', 'king'):
        flash('Только император и короли могут настраивать доходы')
        return redirect(url_for('dashboard'))
    db = get_db()
    target_type = request.form.get('target_type')
    amount = request.form.get('amount', 0)
    if target_type == 'user':
        target = db.execute("SELECT id, username, role, kingdom_name FROM users WHERE id=? AND role != 'emperor'", (request.form.get('user_id'),)).fetchone()
        ok = user_can_manage_income_for_user(manager, target) and set_user_daily_income(db, target['id'], amount)
        if ok:
            create_daily_income_assignment_report(db, parse_money_amount(amount), target['username'], 'власти' if role_is_authority(target['role']) else 'игроку')
    elif target_type == 'kingdom':
        if manager['role'] != 'emperor':
            flash('Короли могут назначать доход только жителям и графам')
            return redirect(url_for('income'))
        target = db.execute('SELECT id, name FROM kingdoms WHERE id=?', (request.form.get('kingdom_id'),)).fetchone()
        ok = target is not None and set_kingdom_daily_income(db, target['id'], amount)
        if ok:
            create_daily_income_assignment_report(db, parse_money_amount(amount), target['name'], 'королевству', kingdom_id=target['id'])
    else:
        ok = False
    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Ежедневный доход назначен')
    else:
        flash('Не удалось назначить ежедневный доход')
    return redirect(url_for('income'))


@app.route('/council')
@login_required
def council():
    if session['user']['role'] != 'emperor':
        flash('Только император может управлять Советом')
        return redirect(url_for('dashboard'))
    db = get_db()
    members = get_council_members(db)
    users = query_db(
        '''SELECT id, username, role, balance, kingdom_name
           FROM users
           WHERE id NOT IN (SELECT user_id FROM imperial_council)
           ORDER BY role, username'''
    )
    return render_template('council.html', members=members, users=users, treasury=get_treasury())


@app.route('/council/add', methods=['POST'])
@login_required
def council_add():
    if session['user']['role'] != 'emperor':
        flash('Только император может управлять Советом')
        return redirect(url_for('dashboard'))
    db = get_db()
    user_id = request.form.get('user_id')
    income = parse_money_amount(request.form.get('council_income', 0))
    if income is None or not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
        flash('Не удалось добавить в Совет')
        return redirect(url_for('council'))
    db.execute(
        'INSERT OR IGNORE INTO imperial_council (user_id, council_income, note) VALUES (?,?,?)',
        (user_id, income, request.form.get('note', '')),
    )
    db.commit()
    flash('Участник добавлен в Совет')
    return redirect(url_for('council'))


@app.route('/council/income', methods=['POST'])
@login_required
def council_income():
    if session['user']['role'] != 'emperor':
        flash('Только император может управлять Советом')
        return redirect(url_for('dashboard'))
    income = parse_money_amount(request.form.get('council_income', 0))
    if income is None:
        flash('Неверная сумма дохода')
        return redirect(url_for('council'))
    db = get_db()
    db.execute(
        'UPDATE imperial_council SET council_income=?, note=? WHERE user_id=?',
        (income, request.form.get('note', ''), request.form.get('user_id')),
    )
    db.commit()
    flash('Доход участника Совета обновлён')
    return redirect(url_for('council'))


@app.route('/council/remove', methods=['POST'])
@login_required
def council_remove():
    if session['user']['role'] != 'emperor':
        flash('Только император может управлять Советом')
        return redirect(url_for('dashboard'))
    db = get_db()
    db.execute('DELETE FROM imperial_council WHERE user_id=?', (request.form.get('user_id'),))
    db.commit()
    flash('Участник удалён из Совета')
    return redirect(url_for('council'))


@app.route('/submit_report', methods=['GET', 'POST'])
@login_required
def submit_report():
    user = session['user']
    defaults = get_report_defaults_for_user(user)
    if request.method == 'POST':
        kingdom_name = request.form.get('kingdom') or defaults.get('kingdom')
        kingdom = query_db('SELECT * FROM kingdoms WHERE name=?', (kingdom_name,), one=True)
        if not kingdom:
            flash('Неизвестное королевство')
            return redirect(url_for('submit_report'))
        try:
            amount_value = float(request.form.get('amount', '0') or 0)
        except ValueError:
            amount_value = 0.0
        db = get_db()
        insert_report(
            db,
            kingdom['id'],
            request.form.get('report_type', 'Финансы'),
            amount_value,
            request.form.get('title', ''),
            request.form.get('description', ''),
            request.form.get('author_name') or defaults.get('author_name') or user['username'],
            request.form.get('recipient_name') or defaults.get('recipient_name') or 'Император',
            request.form.get('nickname') or defaults.get('nickname') or '',
        )
        db.commit()
        send_report_to_telegram()
        flash('Отчёт отправлен')
        return redirect(url_for('dashboard'))
    kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    prefill = {key: request.args.get(key, '') for key in ['kingdom', 'report_type', 'amount', 'title', 'description', 'recipient_name']}
    return render_template('submit_report.html', kingdoms=kingdoms, user_kingdom=defaults.get('kingdom'), report_defaults=defaults, prefill=prefill)


@app.route('/reports')
@login_required
def reports():
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r LEFT JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC')
    return render_template('reports.html', reports=reports)


@app.route('/maps')
@login_required
def maps():
    user = session.get('user', {})
    db = get_db()
    kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    kingdom_maps = [
        {
            'kingdom': k,
            'can_edit': user.get('role') == 'emperor' or user_can_manage_kingdom(user, k['id']),
            'counties': db.execute(
                '''SELECT c.*, u.username AS graf_username, u.daily_income AS graf_daily_income
                   FROM counties c
                   LEFT JOIN users u ON u.id=c.graf_user_id
                   WHERE c.kingdom_name=?
                   ORDER BY c.name''',
                (k['name'],),
            ).fetchall(),
        }
        for k in kingdoms
    ]
    return render_template('maps.html', empire_map=get_empire_map(db), kingdom_maps=kingdom_maps, can_edit_empire=user.get('role') == 'emperor', active_tab=request.args.get('tab', 'empire'))


@app.route('/maps/update', methods=['POST'])
@login_required
def maps_update():
    user = session.get('user', {})
    scope = request.form.get('scope')
    db = get_db()
    if scope == 'empire':
        if user.get('role') != 'emperor':
            flash('Только император может менять карту империи')
            return redirect(url_for('maps'))
        image_path = save_map_upload(request.files.get('map_file'), 'empire-map')
        if image_path:
            set_setting(db, 'empire_map_image', image_path)
        set_setting(db, 'empire_map_notes', request.form.get('map_notes', ''))
    elif scope == 'kingdom':
        kingdom_id = request.form.get('kingdom_id')
        if user.get('role') != 'emperor' and not user_can_manage_kingdom(user, kingdom_id):
            flash('Вы можете менять только карту своего королевства')
            return redirect(url_for('maps'))
        image_path = save_map_upload(request.files.get('map_file'), f'kingdom-{kingdom_id}')
        if image_path:
            db.execute('UPDATE kingdoms SET map_image=? WHERE id=?', (image_path, kingdom_id))
        db.execute('UPDATE kingdoms SET map_notes=? WHERE id=?', (request.form.get('map_notes', ''), kingdom_id))
    else:
        flash('Не удалось обновить карту')
        return redirect(url_for('maps'))
    db.commit()
    flash('Карта обновлена')
    return redirect(url_for('maps'))


@app.route('/cards')
@login_required
def cards():
    return ('Not Found', 404)


@app.route('/cards/create', methods=['POST'])
@login_required
def cards_create():
    return ('Not Found', 404)


@app.route('/cards/toggle_trade/<int:card_id>', methods=['POST'])
@login_required
def cards_toggle_trade(card_id):
    return ('Not Found', 404)


@app.route('/resources/transfer', methods=['POST'])
@login_required
def resources_transfer():
    user = session['user']
    db = get_db()
    ok = apply_resource_transfer_between_kingdoms(
        db,
        request.form.get('from_kingdom_id'),
        request.form.get('to_kingdom_id'),
        request.form.get('tree_amount', 0),
        request.form.get('metal_amount', 0),
        request.form.get('food_amount', 0),
        acting_user=user,
        description=request.form.get('description', ''),
    )
    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Ресурсы переведены')
    else:
        flash('Не удалось перевести ресурсы')
    return redirect(url_for('dashboard'))


@app.route('/build_requests/submit', methods=['POST'])
@login_required
def build_request_submit():
    user = session['user']
    db = get_db()

    ok = submit_building_request(
        db,
        request.form.get('county_id'),
        request.form.get('item_name'),
        0,  # requested_tree_cost - теперь только сумма проекта
        0,  # requested_metal_cost
        0,  # requested_food_cost
        acting_user=user,
        reason=request.form.get('reason', ''),
        requested_kingdom_cash_cost=request.form.get('requested_kingdom_cash_cost', 0),
    )

    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Заявка на постройку отправлена')
    else:
        flash('Не удалось отправить заявку')
    return redirect(url_for('dashboard'))


@app.route('/build_requests/approve', methods=['POST'])
@login_required
def build_request_approve():
    user = session['user']
    if user.get('role') != 'emperor':
        flash('Только император может одобрять постройки')
        return redirect(url_for('dashboard'))
    db = get_db()
    
    # Император вводит ресурсы, которые он тратит
    requested_tree_cost = request.form.get('requested_tree_cost', 0)
    requested_metal_cost = request.form.get('requested_metal_cost', 0)
    requested_food_cost = request.form.get('requested_food_cost', 0)
    
    ok = approve_building_request(
        db,
        request.form.get('request_id'),
        user.get('username'),
        request.form.get('treasury_cash_covered', 0),
        request.form.get('kingdom_cash_cost', 0),
        request.form.get('proposed_tree_income', 0),
        request.form.get('proposed_metal_income', 0),
        request.form.get('proposed_food_income', 0),
        reason=request.form.get('reason', ''),
        requested_tree_cost=requested_tree_cost,
        requested_metal_cost=requested_metal_cost,
        requested_food_cost=requested_food_cost,
    )
    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Постройка одобрена')
    else:
        flash('Не удалось одобрить постройку')
    return redirect(url_for('dashboard'))


@app.route('/build_requests/reject', methods=['POST'])
@login_required
def build_request_reject():
    user = session['user']
    if user.get('role') != 'emperor':
        flash('Только император может отклонять постройки')
        return redirect(url_for('dashboard'))
    db = get_db()
    
    ok = reject_building_request(
        db,
        request.form.get('request_id'),
        user.get('username'),
        reason=request.form.get('reason', ''),
    )
    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Заявка отклонена')
    else:
        flash('Не удалось отклонить заявку')
    return redirect(url_for('build_requests_page'))


@app.route('/build_requests/confirm', methods=['POST'])
@login_required
def build_request_confirm():
    user = session['user']
    db = get_db()
    
    ok = confirm_building_request(
        db,
        request.form.get('request_id'),
        user.get('username'),
    )
    if ok:
        db.commit()
        send_report_to_telegram()
        flash('Строительство началось! Постройка будет готова через 1 час.')
    else:
        flash('Не удалось подтвердить постройку')
    return redirect(url_for('build_requests_page'))


@app.route('/passwords')
@login_required
def passwords_page():
    db = get_db()
    role = session.get('user', {}).get('role')

    kings = []
    grafs = []
    if role == 'emperor':
        kings = db.execute(
            "SELECT u.id, u.username, u.kingdom_name FROM users u WHERE u.role='king' ORDER BY u.kingdom_name, u.username"
        ).fetchall()
        grafs = []
    elif role == 'king':
        king_name = get_user_kingdom_name(session.get('user', {}))
        grafs = db.execute(
            "SELECT u.id, u.username, u.kingdom_name FROM users u WHERE u.role='graf' AND u.kingdom_name=? ORDER BY u.username",
            (king_name,),
        ).fetchall()

    # emperor sees kings, king sees grafs. (graf cannot access)
    return render_template('passwords.html', kings=kings, grafs=grafs)


@app.route('/passwords/kings', methods=['POST'])
@login_required
def passwords_kings_post():
    manager = session['user']
    if manager.get('role') != 'emperor':
        flash('Только император может менять пароли королей')
        return redirect(url_for('passwords_page'))

    db = get_db()
    target = db.execute(
        'SELECT id, username, role FROM users WHERE id=?',
        (request.form.get('user_id'),),
    ).fetchone()

    if not emperor_can_manage_king_password(manager, target):
        flash('Недопустимый король')
        return redirect(url_for('passwords_page'))

    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        new_password = generate_password(target['username'])

    if not set_user_password(db, target['id'], new_password):
        flash('Не удалось сменить пароль')
        return redirect(url_for('passwords_page'))

    db.commit()
    flash(f'Новый пароль для {target["username"]}: {new_password}')
    return redirect(url_for('passwords_page'))


@app.route('/passwords/grafts', methods=['POST'])
@login_required
def passwords_grafts_post():
    manager = session['user']
    if manager.get('role') != 'king':
        flash('Только король может менять пароли графов')
        return redirect(url_for('passwords_page'))

    db = get_db()
    king_name = get_user_kingdom_name(manager)
    target = db.execute(
        'SELECT id, username, role, kingdom_name FROM users WHERE id=?',
        (request.form.get('user_id'),),
    ).fetchone()

    if not target or (target['role'] or '').lower() != 'graf' or (target['kingdom_name'] or '') != king_name:
        flash('Недопустимый граф')
        return redirect(url_for('passwords_page'))

    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        new_password = generate_password(target['username'])

    if not set_user_password(db, target['id'], new_password):
        flash('Не удалось сменить пароль')
        return redirect(url_for('passwords_page'))

    db.commit()
    flash(f'Новый пароль для {target["username"]}: {new_password}')
    return redirect(url_for('passwords_page'))


@app.route('/resources')
@login_required
def resources_page():
    db = get_db()
    kingdoms = query_db('SELECT id, name, tree, metal, food FROM kingdoms ORDER BY name')
    return render_template('resources.html', kingdoms=kingdoms)


@app.route('/resource_income', methods=['GET', 'POST'])
@login_required
def resource_income_page():
    if session.get('user', {}).get('role') != 'emperor':
        flash('Только император может управлять ресурсным доходом')
        return redirect(url_for('dashboard'))

    db = get_db()
    if request.method == 'POST':
        # form fields: kingdom_id, tree_income, metal_income, food_income
        kingdom_id = request.form.get('kingdom_id')
        tree_income = parse_resource_amount(request.form.get('tree_income', 0))
        metal_income = parse_resource_amount(request.form.get('metal_income', 0))
        food_income = parse_resource_amount(request.form.get('food_income', 0))
        if kingdom_id is None or tree_income is None or metal_income is None or food_income is None:
            flash('Неверные данные')
            return redirect(url_for('resource_income_page'))

        kingdom = db.execute('SELECT id FROM kingdoms WHERE id=?', (kingdom_id,)).fetchone()
        if not kingdom:
            flash('Неизвестное королевство')
            return redirect(url_for('resource_income_page'))

        db.execute('UPDATE kingdoms SET tree_income=?, metal_income=?, food_income=? WHERE id=?', (tree_income, metal_income, food_income, kingdom_id))

        insert_report(
            db,
            kingdom_id,
            'Ресурсный доход',
            0,
            'Назначение ресурсного дохода',
            f'Император назначил доход: дерево={tree_income}, металл={metal_income}, продовольствие={food_income}.',
            'Император',
            db.execute('SELECT name FROM kingdoms WHERE id=?', (kingdom_id,)).fetchone()[0],
            'Казна Императора',
        )
        db.commit()
        send_report_to_telegram()
        flash('Ресурсный доход обновлён')
        return redirect(url_for('resource_income_page'))

    kingdoms = query_db('SELECT id, name, tree_income, metal_income, food_income FROM kingdoms ORDER BY name')
    return render_template('resource_income.html', kingdoms=kingdoms, treasury=get_treasury())


@app.route('/build_requests')
@login_required
def build_requests_page():
    user = session['user']
    db = get_db()
    can_approve = user.get('role') == 'emperor'

    my_counties = []
    can_submit = False
    if user.get('role') == 'emperor':
        can_submit = True
    elif user.get('role') == 'king':
        can_submit = True
        my_counties = db.execute(
            "SELECT id, name, kingdom_name FROM counties WHERE kingdom_name=? ORDER BY name",
            (user.get('kingdom_name') or get_user_kingdom_name(user),),
        ).fetchall()
    elif user.get('role') == 'graf':
        # submit only for their own assigned counties
        can_submit = True
        my_counties = db.execute(
            "SELECT id, name, kingdom_name FROM counties WHERE graf_user_id=(SELECT id FROM users WHERE username=? LIMIT 1) ORDER BY name",
            (user.get('username'),),
        ).fetchall()

    building_requests = db.execute(
        "SELECT * FROM building_requests ORDER BY CASE status WHEN 'submitted' THEN 1 WHEN 'emperor_approved' THEN 2 WHEN 'building' THEN 3 ELSE 4 END, created_at DESC LIMIT 50"
    ).fetchall()

    return render_template(
        'build_requests.html',
        can_submit=can_submit,
        can_approve=can_approve,
        my_counties=my_counties,
        building_requests=building_requests,
    )


@app.route('/builds')
@login_required
def builds_page():
    db = get_db()
    # Show only completed buildings (status='active') with city and building name
    builds = db.execute(
        """SELECT county_name, item_name, kingdom_name, created_at, construction_finished_at,
                  requested_tree_cost, requested_metal_cost, requested_food_cost,
                  treasury_cash_covered, kingdom_cash_cost,
                  proposed_tree_income, proposed_metal_income, proposed_food_income
           FROM building_requests 
           WHERE status IN ('active', 'building')
           ORDER BY created_at DESC"""
    ).fetchall()
    return render_template('builds.html', builds=builds)


@app.route('/cards/exchange/<int:card_id>', methods=['POST'])
@login_required
def cards_exchange(card_id):
    return ('Not Found', 404)


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
