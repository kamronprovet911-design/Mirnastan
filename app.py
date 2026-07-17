import sqlite3
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Flask, g, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv('DATABASE', 'budget.db')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'dev-secret')

APP_TIMEZONE = os.getenv('APP_TIMEZONE') or os.getenv('TZ')
DAILY_INCOME_HOUR = 0
DAILY_INCOME_MINUTE = 1
DAILY_INCOME_LAST_DATE_KEY = 'daily_income_last_date'
AUTHORITY_ROLES = ('king', 'graf')
DEFAULT_TREASURY = 200000000000.0
DEFAULT_KINGDOMS = [
    ('Нердия', 1004000000.0),
    ('Астерион', 500000000.0),
    ('Мирноуль', 20000000.0),
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


def ensure_runtime_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        role TEXT,
        password_hash TEXT,
        balance REAL DEFAULT 0,
        daily_income REAL DEFAULT 0
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS kingdoms (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        budget REAL DEFAULT 0,
        daily_income REAL DEFAULT 0
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


def seed_runtime_defaults(db):
    for name, budget in DEFAULT_KINGDOMS:
        db.execute('INSERT OR IGNORE INTO kingdoms (name, budget) VALUES (?,?)', (name, budget))
    ensure_setting(db, 'treasury', str(DEFAULT_TREASURY))
    ensure_setting(db, DAILY_INCOME_LAST_DATE_KEY, '')
    for username, role in DEFAULT_USERS:
        existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing is None:
            db.execute(
                'INSERT INTO users (username, role, password_hash) VALUES (?,?,?)',
                (username, role, generate_password_hash(f'{username}_pass')),
            )


def ensure_runtime_schema(db):
    ensure_runtime_tables(db)
    ensure_column(db, 'users', 'balance', 'REAL DEFAULT 0')
    ensure_column(db, 'users', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(db, 'kingdoms', 'daily_income', 'REAL DEFAULT 0')
    ensure_column(db, 'reports', 'report_type', 'TEXT')
    ensure_column(db, 'reports', 'title', 'TEXT')
    ensure_column(db, 'reports', 'author_name', 'TEXT')
    ensure_column(db, 'reports', 'recipient_name', 'TEXT')
    ensure_column(db, 'reports', 'nickname', 'TEXT')
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


def get_user_kingdom_name(user):
    username = (user or {}).get('username', '')
    kingdom_map = {
        'king_nerdia': 'Нердия',
        'king_asterion': 'Астерион',
        'king_mirnoul': 'Мирноуль',
        'graf_nerdia_1': 'Нердия',
        'graf_asterion_1': 'Астерион',
        'graf_mirnoul_1': 'Мирноуль',
    }
    return kingdom_map.get(username)


def user_can_manage_kingdom(user, kingdom_id):
    if not role_can_manage_money((user or {}).get('role')):
        return False
    if (user or {}).get('role', '').lower() == 'emperor':
        return True
    kingdom_name = get_user_kingdom_name(user)
    if not kingdom_name:
        return False
    kingdom = query_db('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,), one=True)
    return kingdom is not None and kingdom['name'] == kingdom_name


def get_user_balance(db, username):
    if not username:
        return 0.0
    row = db.execute("SELECT balance FROM users WHERE username=?", (username,)).fetchone()
    if row and row[0] is not None:
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def get_user_kingdom(db, user):
    kingdom_name = get_user_kingdom_name(user)
    if not kingdom_name:
        return None
    return db.execute('SELECT * FROM kingdoms WHERE name=?', (kingdom_name,)).fetchone()


def apply_people_expense(db, amount, description='', acting_user=None):
    amount = float(amount)
    if amount <= 0:
        return False
    acting_user = acting_user or {}
    role = (acting_user or {}).get('role', '').lower()
    username = (acting_user or {}).get('username')
    report_kingdom_id = None

    if role == 'emperor' or not username:
        treasury_row = db.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()
        treasury = float(treasury_row[0]) if treasury_row and treasury_row[0] is not None else 0.0
        if treasury < amount:
            return False
        db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
        from_user_id = None
        author_name = 'Император'
        nickname = 'Казна Императора'
    elif role in AUTHORITY_ROLES:
        kingdom = get_user_kingdom(db, acting_user)
        if not kingdom:
            return False
        if float(kingdom['budget'] or 0) < amount:
            return False
        db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, kingdom['id']))
        from_user_id = None
        report_kingdom_id = kingdom['id']
        title = 'Король' if role == 'king' else 'Граф'
        author_name = f'{title} {kingdom["name"]}'
        nickname = f'Казна {kingdom["name"]}'
    else:
        balance = get_user_balance(db, username)
        if balance < amount:
            return False
        db.execute("UPDATE users SET balance = balance - ? WHERE username=?", (amount, username))
        user_row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        from_user_id = user_row[0] if user_row else None
        author_name = username or 'Игрок'
        nickname = username or 'Личный баланс'

    db.execute("INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)",
               (report_kingdom_id, 'Расход на народ', -amount, 'Трата на народ', f'Средства направлены на нужды населения | {description or "обеспечение благосостояния"}', author_name, 'Народ', nickname))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (from_user_id, report_kingdom_id, -amount, description or 'Расход на народ'))
    return True


def apply_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, amount, description='', acting_user=None):
    amount = float(amount)
    if amount <= 0:
        return False
    from_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (from_kingdom_id,)).fetchone()
    to_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (to_kingdom_id,)).fetchone()
    if not from_kingdom or not to_kingdom:
        return False
    acting_user = acting_user or {}
    role = (acting_user or {}).get('role', '').lower()
    username = (acting_user or {}).get('username')

    if role == 'emperor' or not username:
        from_budget = float(from_kingdom[2]) if len(from_kingdom) > 2 else float(from_kingdom[1])
        if from_budget < amount:
            return False
        author_name = 'Император'
        nickname = 'Казна Императора'
    else:
        balance = get_user_balance(db, username)
        if balance < amount:
            return False
        db.execute("UPDATE users SET balance = balance - ? WHERE username=?", (amount, username))
        author_name = username or 'Игрок'
        nickname = username or 'Личный баланс'

    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, from_kingdom_id))
    db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, to_kingdom_id))
    db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
               (to_kingdom_id, 'Перевод', amount, 'Перевод между королевствами', f'Переведено {amount} | {description or "перераспределение ресурсов"}', author_name, to_kingdom[1], nickname))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, to_kingdom_id, amount, description or 'Перевод между королевствами'))
    return True


def get_report_defaults_for_user(user):
    username = (user or {}).get('username', '')
    role = (user or {}).get('role', '').lower()

    kingdom_map = {
        'king_nerdia': 'Нердия',
        'king_asterion': 'Астерион',
        'king_mirnoul': 'Мирноуль',
        'graf_nerdia_1': 'Нердия',
        'graf_asterion_1': 'Астерион',
        'graf_mirnoul_1': 'Мирноуль',
    }

    kingdom_name = kingdom_map.get(username)
    if not kingdom_name:
        return {
            'kingdom': None,
            'author_name': None,
            'recipient_name': None,
            'nickname': None,
        }

    role_title = {
        'emperor': 'Император',
        'king': 'Король',
        'graf': 'Граф',
    }.get(role, 'Должность')

    if role == 'king':
        author_name = f'Король {kingdom_name}'
        recipient_name = 'Император'
        nickname = f'Король {kingdom_name}'
    elif role == 'graf':
        author_name = f'Граф {kingdom_name}'
        recipient_name = f'Король {kingdom_name}'
        nickname = f'Граф {kingdom_name}'
    else:
        author_name = role_title
        recipient_name = 'Совет'
        nickname = role_title

    return {
        'kingdom': kingdom_name,
        'author_name': author_name,
        'recipient_name': recipient_name,
        'nickname': nickname,
    }


def get_treasury():
    row = query_db("SELECT value FROM settings WHERE key='treasury'", one=True)
    if row and row['value'] is not None:
        try:
            return float(row['value'])
        except (TypeError, ValueError):
            pass
    return DEFAULT_TREASURY


def send_report_to_telegram():
    try:
        import telegram_bot
        telegram_bot.DB = DB_PATH
        telegram_bot.process_pending_reports()
    except Exception as exc:
        print('Telegram send failed:', exc)


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


def set_setting(db, key, value):
    cur = db.execute('UPDATE settings SET value=? WHERE key=?', (str(value), key))
    if cur.rowcount == 0:
        db.execute('INSERT INTO settings (key, value) VALUES (?,?)', (key, str(value)))


def get_treasury_from_db(db):
    return get_setting_float(db, 'treasury', DEFAULT_TREASURY)


def parse_money_amount(value):
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return amount


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


def role_is_authority(role):
    return (role or '').lower() in AUTHORITY_ROLES


def create_daily_income_assignment_report(db, amount, recipient_name, target_kind, kingdom_id=None):
    amount = float(amount)
    action = 'отключен' if amount == 0 else 'назначен'
    db.execute(
        'INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
        (
            kingdom_id,
            'Назначение дохода',
            amount,
            'Настройка ежедневного дохода',
            f'Ежедневный доход {action}: {target_kind} {recipient_name} | сумма {amount} каждый день в 00:01',
            'Император',
            recipient_name,
            'Казна Императора',
        ),
    )


def apply_bulk_income(db, user_amount=0, kingdom_amount=0, description=''):
    user_amount = parse_money_amount(user_amount)
    kingdom_amount = parse_money_amount(kingdom_amount)
    if user_amount is None or kingdom_amount is None:
        return False
    users = db.execute("SELECT id, username FROM users WHERE role != 'emperor'").fetchall()
    kingdoms = db.execute('SELECT id, name FROM kingdoms').fetchall()
    total = (user_amount * len(users)) + (kingdom_amount * len(kingdoms))
    if total <= 0:
        return False
    if get_treasury_from_db(db) < total:
        return False
    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (total,))
    if user_amount > 0:
        db.execute("UPDATE users SET balance = balance + ? WHERE role != 'emperor'", (user_amount,))
    if kingdom_amount > 0:
        db.execute('UPDATE kingdoms SET budget = budget + ?', (kingdom_amount,))
        for kingdom in kingdoms:
            db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
                       (None, kingdom['id'], kingdom_amount, description or 'Ежедневный доход королевству'))
    db.execute("INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)",
               (None, 'Ежедневный доход', total, 'Ежедневный доход', f'Игрокам: {user_amount}, королевствам: {kingdom_amount} | {description or "выплата дохода"}', 'Император', 'Игроки и королевства', 'Казна Императора'))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
               (None, None, total, description or 'Ежедневный доход'))
    return True


def apply_daily_income(db, amount, description=''):
    return apply_bulk_income(db, amount, 0, description)


def is_daily_income_time(now):
    return now.hour == DAILY_INCOME_HOUR and now.minute == DAILY_INCOME_MINUTE


def get_configured_income_recipients(db):
    users = db.execute("SELECT id, username, role, daily_income FROM users WHERE role != 'emperor' AND COALESCE(daily_income, 0) > 0").fetchall()
    kingdoms = db.execute('SELECT id, name, daily_income FROM kingdoms WHERE COALESCE(daily_income, 0) > 0').fetchall()
    return users, kingdoms


def apply_configured_daily_income(db, run_date, description=''):
    if get_setting_value(db, DAILY_INCOME_LAST_DATE_KEY, '') == run_date:
        return False
    users, kingdoms = get_configured_income_recipients(db)
    player_total = sum(float(user['daily_income'] or 0) for user in users if not role_is_authority(user['role']))
    authority_total = sum(float(user['daily_income'] or 0) for user in users if role_is_authority(user['role']))
    kingdom_total = sum(float(kingdom['daily_income'] or 0) for kingdom in kingdoms)
    total = player_total + authority_total + kingdom_total
    if total <= 0:
        return False
    if get_treasury_from_db(db) < total:
        return False

    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (total,))
    for user in users:
        db.execute('UPDATE users SET balance = balance + ? WHERE id=?', (float(user['daily_income']), user['id']))
    for kingdom in kingdoms:
        kingdom_amount = float(kingdom['daily_income'])
        db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (kingdom_amount, kingdom['id']))
        db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
                   (None, kingdom['id'], kingdom_amount, description or 'Ежедневный доход королевству'))
    player_lines = [f"{user['username']}: {float(user['daily_income'])}" for user in users if not role_is_authority(user['role'])]
    authority_lines = [f"{user['username']}: {float(user['daily_income'])}" for user in users if role_is_authority(user['role'])]
    kingdom_lines = [f"{kingdom['name']}: {float(kingdom['daily_income'])}" for kingdom in kingdoms]
    detail_parts = [
        f'Игрокам: {player_total}',
        f'Власти: {authority_total}',
        f'Королевствам: {kingdom_total}',
    ]
    if player_lines:
        detail_parts.append('игроки: ' + ', '.join(player_lines))
    if authority_lines:
        detail_parts.append('власть: ' + ', '.join(authority_lines))
    if kingdom_lines:
        detail_parts.append('королевства: ' + ', '.join(kingdom_lines))
    db.execute("INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)",
               (None, 'Ежедневный доход', total, 'Ежедневный доход', f'{"; ".join(detail_parts)} | {description or "автоматическая выплата в 00:01"}', 'Император', 'Игроки, власть и королевства', 'Казна Императора'))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)',
               (None, None, total, description or 'Ежедневный доход'))
    set_setting(db, DAILY_INCOME_LAST_DATE_KEY, run_date)
    return True


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

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'peasant')
        if not username or not password:
            flash('Введите логин и пароль')
            return redirect(url_for('register'))
        if get_user(username):
            flash('Пользователь с таким логином уже существует')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password)
        db = get_db()
        db.execute('INSERT INTO users (username, role, password_hash) VALUES (?,?,?)', (username, role, password_hash))
        db.commit()
        flash('Регистрация выполнена. Теперь войдите в систему.')
        return redirect(url_for('login'))
    roles = [
        ('peasant', 'Крестьянин'),
        ('citizen', 'Житель'),
        ('merchant', 'Торговец'),
        ('artisan', 'Ремесленник'),
    ]
    return render_template('register.html', roles=roles)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = dict(username=user['username'], role=user['role'], balance=user['balance'] or 0)
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
    db = get_db()
    kingdoms = query_db('SELECT * FROM kingdoms')
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r LEFT JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC LIMIT 10')
    treasury = get_treasury()
    return render_template('dashboard.html', kingdoms=kingdoms, reports=reports, treasury=treasury)


@app.route('/income')
@login_required
def income():
    user = session['user']
    if user['role'] != 'emperor':
        flash('Только император может управлять доходами')
        return redirect(url_for('dashboard'))
    player_users = query_db(
        "SELECT id, username, role, balance, daily_income FROM users WHERE role NOT IN ('emperor','king','graf') ORDER BY username"
    )
    authority_users = query_db(
        "SELECT id, username, role, balance, daily_income FROM users WHERE role IN ('king','graf') ORDER BY role, username"
    )
    kingdoms = query_db('SELECT * FROM kingdoms ORDER BY name')
    treasury = get_treasury()
    return render_template(
        'income.html',
        player_users=player_users,
        authority_users=authority_users,
        kingdoms=kingdoms,
        treasury=treasury,
    )

@app.route('/allocate', methods=['POST'])
@login_required
def allocate():
    user = session['user']
    if user['role'] != 'emperor':
        flash('Только император может выделять бюджет')
        return redirect(url_for('dashboard'))
    kingdom_id = request.form['kingdom_id']
    amount = float(request.form['amount'])
    desc = request.form.get('description','')
    db = get_db()
    kingdom = query_db('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,), one=True)
    if not kingdom:
        flash('Неизвестное королевство')
        return redirect(url_for('dashboard'))
    db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, kingdom_id))
    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, kingdom_id, amount, desc))
    db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
               (kingdom_id, 'Финансы', amount, 'Выделение бюджета', f'Выделено {amount} | {desc}', 'Император', kingdom['name'], 'Казна Императора'))
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
    kingdom_id = request.form['kingdom_id']
    amount = float(request.form['amount'])
    desc = request.form.get('description','')
    db = get_db()
    kingdom = query_db('SELECT * FROM kingdoms WHERE id=?', (kingdom_id,), one=True)
    if not kingdom:
        flash('Неизвестное королевство')
        return redirect(url_for('dashboard'))
    if kingdom['budget'] < amount:
        flash('Недостаточно средств для списания')
        return redirect(url_for('dashboard'))
    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, kingdom_id))
    db.execute("UPDATE settings SET value = CAST(value AS REAL) + ? WHERE key='treasury'", (amount,))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, kingdom_id, -amount, desc))
    db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
               (kingdom_id, 'Финансы', -amount, 'Списание бюджета', f'Списано {amount} | {desc}', 'Император', kingdom['name'], 'Казна Императора'))
    db.commit()
    send_report_to_telegram()
    flash('Средства списаны')
    return redirect(url_for('dashboard'))

@app.route('/people_expense', methods=['POST'])
@login_required
def people_expense():
    user = session['user']
    if not role_can_manage_money(user['role']):
        flash('У вас нет доступа к финансовым операциям')
        return redirect(url_for('dashboard'))
    amount = float(request.form.get('amount', 0) or 0)
    description = request.form.get('description', '')
    db = get_db()
    if apply_people_expense(db, amount, description, acting_user=user):
        db.commit()
        session['user']['balance'] = get_user_balance(db, user['username']) if user['username'] else 0
        send_report_to_telegram()
        flash('Средства направлены на народ')
    else:
        flash('Недостаточно средств в казне')
    return redirect(url_for('dashboard'))

@app.route('/transfer_between_kingdoms', methods=['POST'])
@login_required
def transfer_between_kingdoms():
    user = session['user']
    if not role_can_manage_money(user['role']):
        flash('У вас нет доступа к финансовым операциям')
        return redirect(url_for('dashboard'))
    from_kingdom_id = request.form.get('from_kingdom_id')
    to_kingdom_id = request.form.get('to_kingdom_id')
    if user['role'] != 'emperor':
        if not user_can_manage_kingdom(user, from_kingdom_id):
            flash('Вы можете переводить средства только из своего королевства')
            return redirect(url_for('dashboard'))
    amount = float(request.form.get('amount', 0) or 0)
    description = request.form.get('description', '')
    db = get_db()
    if apply_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, amount, description, acting_user=user):
        db.commit()
        session['user']['balance'] = get_user_balance(db, user['username']) if user['username'] else 0
        send_report_to_telegram()
        flash('Перевод выполнен')
    else:
        flash('Невозможно выполнить перевод')
    return redirect(url_for('dashboard'))

@app.route('/daily_income', methods=['POST'])
@login_required
def daily_income():
    user = session['user']
    if user['role'] != 'emperor':
        flash('Только император может выдавать доход')
        return redirect(url_for('dashboard'))
    target_type = request.form.get('target_type')
    amount = request.form.get('amount', 0)
    db = get_db()
    if target_type == 'user':
        target = db.execute("SELECT id, username, role FROM users WHERE id=? AND role != 'emperor'", (request.form.get('user_id'),)).fetchone()
        ok = target is not None and set_user_daily_income(db, target['id'], amount)
        if ok:
            kind = 'власти' if role_is_authority(target['role']) else 'игроку'
            create_daily_income_assignment_report(db, parse_money_amount(amount), target['username'], kind)
    elif target_type == 'kingdom':
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


@app.route('/submit_report', methods=['GET','POST'])
@login_required
def submit_report():
    user = session['user']
    kingdom_map = {'king_nerdia':'Нердия','king_asterion':'Астерион','king_mirnoul':'Мирноуль'}
    user_kingdom = kingdom_map.get(user['username'])
    defaults = get_report_defaults_for_user(user)
    if request.method == 'POST':
        kingdom_name = request.form.get('kingdom') or defaults.get('kingdom') or user_kingdom
        kingdom = query_db('SELECT * FROM kingdoms WHERE name=?', (kingdom_name,), one=True)
        if not kingdom:
            flash('Неизвестное королевство')
            return redirect(url_for('submit_report'))
        report_type = request.form.get('report_type', 'Финансы')
        amount = request.form.get('amount', '0')
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        author_name = request.form.get('author_name') or defaults.get('author_name') or user['username']
        recipient_name = request.form.get('recipient_name') or defaults.get('recipient_name') or 'Император'
        nickname = request.form.get('nickname') or defaults.get('nickname') or ''
        try:
            amount_value = float(amount) if amount else 0.0
        except ValueError:
            amount_value = 0.0
        db = get_db()
        db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)', (kingdom['id'], report_type, amount_value, title, description, author_name, recipient_name, nickname))
        db.commit()
        send_report_to_telegram()
        flash('Отчёт отправлен')
        return redirect(url_for('dashboard'))
    kingdoms = query_db('SELECT * FROM kingdoms')
    return render_template('submit_report.html', kingdoms=kingdoms, user_kingdom=user_kingdom, report_defaults=defaults)

@app.route('/reports')
@login_required
def reports():
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r LEFT JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC')
    return render_template('reports.html', reports=reports)

if __name__=='__main__':
    import os
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
