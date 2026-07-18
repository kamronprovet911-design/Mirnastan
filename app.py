import sqlite3
import os
from flask import Flask, g, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
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
    try:
        columns = [row[1] for row in db.execute('PRAGMA table_info(users)')]
        if 'balance' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0')
            db.commit()
    except Exception:
        pass
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


def apply_people_expense(db, amount, description='', acting_user=None):
    amount = float(amount)
    if amount <= 0:
        return False
    acting_user = acting_user or {}
    role = (acting_user or {}).get('role', '').lower()
    username = (acting_user or {}).get('username')

    if role == 'emperor' or not username:
        treasury_row = db.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()
        treasury = float(treasury_row[0]) if treasury_row and treasury_row[0] is not None else 0.0
        if treasury < amount:
            return False
        db.execute("UPDATE settings SET value = CAST(value AS REAL) - ? WHERE key='treasury'", (amount,))
        from_user_id = None
        author_name = 'Император'
        nickname = 'Казна Императора'
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
               (None, 'Расход на народ', -amount, 'Трата на народ', f'Средства направлены на нужды населения | {description or "обеспечение благосостояния"}', author_name, 'Народ', nickname))
    db.execute('INSERT INTO transactions (from_user, to_kingdom, amount, description) VALUES (?,?,?,?)', (from_user_id, None, -amount, description or 'Расход на народ'))
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
            session['user'] = dict(username=user['username'], role=user['role'], balance=user.get('balance', 0))
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

@app.route('/income')
@login_required
def income():
    if session['user']['role'] != 'emperor':
        flash('Только император может настраивать доходы')
        return redirect(url_for('dashboard'))
    
    player_users = query_db('SELECT * FROM users WHERE role IN (?,?)', ('peasant', 'citizen'))
    authority_users = query_db('SELECT * FROM users WHERE role IN (?,?,?)', ('emperor', 'king', 'graf'))
    kingdoms = query_db('SELECT * FROM kingdoms')
    treasury = get_treasury()
    
    return render_template('income.html', player_users=player_users, authority_users=authority_users, kingdoms=kingdoms, treasury=treasury)

@app.route('/daily_income', methods=['POST'])
@login_required
def daily_income():
    if session['user']['role'] != 'emperor':
        flash('Только император может настраивать доходы')
        return redirect(url_for('dashboard'))
    
    target_type = request.form.get('target_type')
    amount = float(request.form.get('amount', 0))
    db = get_db()
    
    if target_type == 'user':
        user_id = request.form.get('user_id')
        db.execute('UPDATE users SET daily_income=? WHERE id=?', (amount, user_id))
    elif target_type == 'kingdom':
        kingdom_id = request.form.get('kingdom_id')
        db.execute('UPDATE kingdoms SET daily_income=? WHERE id=?', (amount, kingdom_id))
    
    db.commit()
    flash('Доход обновлён')
    return redirect(url_for('income'))

@app.route('/update_treasury', methods=['POST'])
@login_required
def update_treasury():
    if session['user']['role'] != 'emperor':
        flash('Только император может менять казну')
        return redirect(url_for('dashboard'))
    
    amount = float(request.form.get('amount', 0))
    db = get_db()
    db.execute("UPDATE settings SET value=? WHERE key='treasury'", (str(amount),))
    db.commit()
    flash('Казна обновлена')
    return redirect(url_for('dashboard'))

@app.route('/maps')
@login_required
def maps():
    user = session.get('user', {})
    active_tab = request.args.get('tab', 'empire')
    
    kingdoms = query_db('SELECT * FROM kingdoms')
    
    empire_map_image = query_db("SELECT value FROM settings WHERE key='empire_map_image'", one=True)
    empire_map_notes = query_db("SELECT value FROM settings WHERE key='empire_map_notes'", one=True)
    
    empire_map = {
        'image': empire_map_image['value'] if empire_map_image and empire_map_image['value'] else 'maps/mirnastan.jpg',
        'title': 'Империя Мирнастан',
        'notes': empire_map_notes['value'] if empire_map_notes and empire_map_notes['value'] else 'Общая карта империи с тремя провинциями: Астерион, Нердия и Мирноуль.'
    }
    
    can_edit_empire = user.get('role') == 'emperor'
    
    kingdom_maps = []
    for k in kingdoms:
        can_edit = user.get('role') == 'emperor' or user_can_manage_kingdom(user, k['id'])
        kingdom_maps.append({
            'kingdom': k,
            'can_edit': can_edit
        })
    
    return render_template('maps.html', 
                          empire_map=empire_map, 
                          kingdom_maps=kingdom_maps, 
                          can_edit_empire=can_edit_empire,
                          active_tab=active_tab)

@app.route('/maps/update', methods=['POST'])
@login_required
def maps_update():
    user = session.get('user', {})
    scope = request.form.get('scope')
    
    if scope == 'empire' and user.get('role') != 'emperor':
        flash('Только император может менять карту империи')
        return redirect(url_for('maps'))
    
    if scope == 'kingdom':
        kingdom_id = request.form.get('kingdom_id')
        if user.get('role') != 'emperor' and not user_can_manage_kingdom(user, kingdom_id):
            flash('Вы можете менять только карту своего королевства')
            return redirect(url_for('maps'))
    
    db = get_db()
    
    if 'map_file' in request.files:
        file = request.files['map_file']
        if file and file.filename:
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(app.static_folder, 'maps')
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            file.save(filepath)
            
            if scope == 'empire':
                db.execute("UPDATE settings SET value=? WHERE key='empire_map_image'", (f'maps/{filename}',))
            elif scope == 'kingdom':
                kingdom_id = request.form.get('kingdom_id')
                db.execute("UPDATE kingdoms SET map_image=? WHERE id=?", (f'maps/{filename}', kingdom_id))
    
    map_notes = request.form.get('map_notes', '')
    if scope == 'empire':
        db.execute("UPDATE settings SET value=? WHERE key='empire_map_notes'", (map_notes,))
    elif scope == 'kingdom':
        kingdom_id = request.form.get('kingdom_id')
        db.execute("UPDATE kingdoms SET map_notes=? WHERE id=?", (map_notes, kingdom_id))
    
    db.commit()
    flash('Карта обновлена')
    return redirect(url_for('maps'))

@app.route('/cards')
@login_required
def cards():
    user = session.get('user', {})
    db = get_db()
    
    user_id = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    user_id = user_id[0] if user_id else None
    
    my_cards = query_db('SELECT * FROM cards WHERE owner_id=?', (user_id,)) if user_id else []
    trade_cards = query_db('SELECT c.*, u.username as owner_name FROM cards c JOIN users u ON c.owner_id=u.id WHERE c.for_trade=1')
    
    return render_template('cards.html', my_cards=my_cards, trade_cards=trade_cards)

@app.route('/cards/create', methods=['POST'])
@login_required
def cards_create():
    user = session.get('user', {})
    if user.get('role') not in ['emperor', 'king']:
        flash('Только император и короли могут создавать карты')
        return redirect(url_for('cards'))
    
    db = get_db()
    user_id = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    user_id = user_id[0] if user_id else None
    
    name = request.form.get('name', '')
    description = request.form.get('description', '')
    card_type = request.form.get('card_type', 'action')
    rarity = request.form.get('rarity', 'common')
    effect = request.form.get('effect', '')
    
    if name:
        db.execute('INSERT INTO cards (name, description, card_type, rarity, effect, owner_id) VALUES (?,?,?,?,?,?)',
                   (name, description, card_type, rarity, effect, user_id))
        db.commit()
        flash('Карта создана')
    
    return redirect(url_for('cards'))

@app.route('/cards/toggle_trade/<int:card_id>', methods=['POST'])
@login_required
def cards_toggle_trade(card_id):
    user = session.get('user', {})
    db = get_db()
    
    card = query_db('SELECT * FROM cards WHERE id=?', (card_id,), one=True)
    if not card:
        flash('Карта не найдена')
        return redirect(url_for('cards'))
    
    user_id = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    user_id = user_id[0] if user_id else None
    
    if card['owner_id'] != user_id:
        flash('Это не ваша карта')
        return redirect(url_for('cards'))
    
    new_trade_status = 0 if card['for_trade'] else 1
    db.execute('UPDATE cards SET for_trade=? WHERE id=?', (new_trade_status, card_id))
    db.commit()
    flash('Статус обмена изменён')
    return redirect(url_for('cards'))

@app.route('/cards/exchange/<int:card_id>', methods=['POST'])
@login_required
def cards_exchange(card_id):
    user = session.get('user', {})
    db = get_db()
    
    card = query_db('SELECT * FROM cards WHERE id=?', (card_id,), one=True)
    if not card or not card['for_trade']:
        flash('Карта недоступна для обмена')
        return redirect(url_for('cards'))
    
    user_id = db.execute('SELECT id FROM users WHERE username=?', (user.get('username'),)).fetchone()
    user_id = user_id[0] if user_id else None
    
    if card['owner_id'] == user_id:
        flash('Нельзя обменять свою же карту')
        return redirect(url_for('cards'))
    
    db.execute('UPDATE cards SET owner_id=?, for_trade=0 WHERE id=?', (user_id, card_id))
    db.commit()
    
    author_name = user.get('username') or 'Игрок'
    recipient_row = db.execute('SELECT username FROM users WHERE id=?', (card['owner_id'],)).fetchone()
    recipient_name = recipient_row[0] if recipient_row else 'Неизвестно'
    
    db.execute('INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (?,?,?,?,?,?,?,?)',
               (None, 'Обмен карт', 0, f'Обмен карты: {card["name"]}', f'Карта "{card["name"]}" ({card["rarity"]}) обменена от {recipient_name} к {author_name}', author_name, recipient_name, f'Карта: {card["name"]}'))
    db.commit()
    send_report_to_telegram()
    
    flash('Карта получена!')
    return redirect(url_for('cards'))

if __name__=='__main__':
    import os
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)