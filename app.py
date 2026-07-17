import sqlite3
import os
from flask import Flask, g, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv('DATABASE', 'budget.db')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET', 'dev-secret')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
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
    return (role or '').lower() in {'emperor', 'king', 'graf'}


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


def apply_people_expense(db, amount, description=''):
    amount = float(amount)
    if amount <= 0:
        return False
    treasury_row = db.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()
    treasury = float(treasury_row[0]) if treasury_row and treasury_row[0] is not None else 0.0
    if treasury < amount:
        return False
    db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
    db.execute("INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)",
               (None, 'Расход на народ', -amount, 'Трата на народ', f'Средства направлены на нужды населения | {description or "обеспечение благосостояния"}', 'Император', 'Народ', 'Казна Императора'))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (None, None, -amount, description or 'Расход на народ'))
    return True


def apply_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, amount, description=''):
    amount = float(amount)
    if amount <= 0:
        return False
    from_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (from_kingdom_id,)).fetchone()
    to_kingdom = db.execute('SELECT * FROM kingdoms WHERE id=?', (to_kingdom_id,)).fetchone()
    if not from_kingdom or not to_kingdom:
        return False
    from_budget = float(from_kingdom[2]) if len(from_kingdom) > 2 else float(from_kingdom[1])
    to_budget = float(to_kingdom[2]) if len(to_kingdom) > 2 else float(to_kingdom[1])
    if from_budget < amount:
        return False
    db.execute('UPDATE kingdoms SET budget = budget - ? WHERE id=?', (amount, from_kingdom_id))
    db.execute('UPDATE kingdoms SET budget = budget + ? WHERE id=?', (amount, to_kingdom_id))
    db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
               (to_kingdom_id, 'Перевод', amount, 'Перевод между королевствами', f'Переведено {amount} | {description or "перераспределение ресурсов"}', 'Император', to_kingdom[1], 'Казна Императора'))
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
    return 200000000000.0


def send_report_to_telegram():
    try:
        import telegram_bot
        telegram_bot.process_pending_reports()
    except Exception as exc:
        print('Telegram send failed:', exc)


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

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = dict(username=user['username'], role=user['role'])
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
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC LIMIT 10')
    treasury = get_treasury()
    return render_template('dashboard.html', kingdoms=kingdoms, reports=reports, treasury=treasury)

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
    if apply_people_expense(db, amount, description):
        db.commit()
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
    if apply_transfer_between_kingdoms(db, from_kingdom_id, to_kingdom_id, amount, description):
        db.commit()
        send_report_to_telegram()
        flash('Перевод выполнен')
    else:
        flash('Невозможно выполнить перевод')
    return redirect(url_for('dashboard'))

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
    reports = query_db('SELECT r.*, k.name as kingdom_name FROM reports r JOIN kingdoms k ON r.kingdom_id=k.id ORDER BY r.created_at DESC')
    return render_template('reports.html', reports=reports)

if __name__=='__main__':
    import os
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)