import os
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
AUTHORITY_ROLES = ('king', 'graf')
DEFAULT_TREASURY = 10000000000.0
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
        kingdom_name TEXT DEFAULT ''
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS kingdoms (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        budget REAL DEFAULT 0,
        daily_income REAL DEFAULT 0,
        map_image TEXT DEFAULT '',
        map_notes TEXT DEFAULT ''
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


def ensure_runtime_schema(db):
    ensure_runtime_tables(db)
    ensure_column(db, 'users', 'balance', 'REAL DEFAULT 0')
    ensure_column(db, 'users', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(db, 'users', 'kingdom_name', "TEXT DEFAULT ''")
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
        paid = apply_configured_daily_income(db, now.date().isoformat(), 'автоматическая выплата в 00:01')
        if paid:
            db.commit()
            send_report_to_telegram()
        return paid
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
        player_users = query_db("SELECT id, username, role, balance, daily_income, kingdom_name FROM users WHERE role NOT IN ('emperor','king','graf') ORDER BY username")
        authority_users = query_db("SELECT id, username, role, balance, daily_income, kingdom_name FROM users WHERE role IN ('king','graf') ORDER BY role, username")
        kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    else:
        kingdom_name = get_user_kingdom_name(user)
        player_users = query_db(
            "SELECT id, username, role, balance, daily_income, kingdom_name FROM users WHERE role NOT IN ('emperor','king','graf') AND kingdom_name=? ORDER BY username",
            (kingdom_name,),
        )
        authority_users = query_db(
            "SELECT id, username, role, balance, daily_income, kingdom_name FROM users WHERE role='graf' AND kingdom_name=? ORDER BY username",
            (kingdom_name,),
        )
        kingdoms = []
    return render_template('income.html', player_users=player_users, authority_users=authority_users, kingdoms=kingdoms, treasury=get_treasury(), can_manage_kingdoms=user['role'] == 'emperor')


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
    kingdom_maps = [{'kingdom': k, 'can_edit': user.get('role') == 'emperor' or user_can_manage_kingdom(user, k['id'])} for k in kingdoms]
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
    user = session.get('user', {})
    db = get_db()
    user_row = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    user_id = user_row[0] if user_row else None
    my_cards = query_db('SELECT * FROM cards WHERE owner_id=? ORDER BY created_at DESC', (user_id,)) if user_id else []
    trade_cards = query_db('SELECT c.*, u.username as owner_name FROM cards c JOIN users u ON c.owner_id=u.id WHERE c.for_trade=1 AND c.owner_id != ? ORDER BY c.created_at DESC', (user_id or 0,))
    return render_template('cards.html', my_cards=my_cards, trade_cards=trade_cards)


@app.route('/cards/create', methods=['POST'])
@login_required
def cards_create():
    user = session.get('user', {})
    if user.get('role') not in ['emperor', 'king']:
        flash('Только император и короли могут создавать карты')
        return redirect(url_for('cards'))
    db = get_db()
    user_row = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    if not user_row or not request.form.get('name'):
        flash('Название карты обязательно')
        return redirect(url_for('cards'))
    db.execute(
        'INSERT INTO cards (name, description, card_type, rarity, effect, owner_id) VALUES (?,?,?,?,?,?)',
        (request.form.get('name'), request.form.get('description', ''), request.form.get('card_type', 'action'), request.form.get('rarity', 'common'), request.form.get('effect', ''), user_row[0]),
    )
    db.commit()
    flash('Карта создана')
    return redirect(url_for('cards'))


@app.route('/cards/toggle_trade/<int:card_id>', methods=['POST'])
@login_required
def cards_toggle_trade(card_id):
    user = session.get('user', {})
    db = get_db()
    user_row = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    card = db.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone()
    if not user_row or not card or card['owner_id'] != user_row[0]:
        flash('Это не ваша карта')
        return redirect(url_for('cards'))
    db.execute('UPDATE cards SET for_trade=? WHERE id=?', (0 if card['for_trade'] else 1, card_id))
    db.commit()
    flash('Статус обмена изменён')
    return redirect(url_for('cards'))


@app.route('/cards/exchange/<int:card_id>', methods=['POST'])
@login_required
def cards_exchange(card_id):
    user = session.get('user', {})
    db = get_db()
    user_row = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    card = db.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone()
    if not user_row or not card or not card['for_trade'] or card['owner_id'] == user_row[0]:
        flash('Карта недоступна для обмена')
        return redirect(url_for('cards'))
    previous_owner = db.execute('SELECT username FROM users WHERE id=?', (card['owner_id'],)).fetchone()
    db.execute('UPDATE cards SET owner_id=?, for_trade=0 WHERE id=?', (user_row[0], card_id))
    insert_report(db, None, 'Обмен карт', 0, f'Обмен карты: {card["name"]}', f'Карта "{card["name"]}" перешла от {previous_owner[0] if previous_owner else "неизвестно"} к {user.get("username")}', user.get('username'), previous_owner[0] if previous_owner else 'Неизвестно', f'Карта: {card["name"]}')
    db.commit()
    send_report_to_telegram()
    flash('Карта получена')
    return redirect(url_for('cards'))


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
