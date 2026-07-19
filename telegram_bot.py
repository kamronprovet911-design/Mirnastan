import os
import time
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()
DB = os.getenv('DATABASE','budget.db')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
THREAD_MAP = {
    'Нердия': os.getenv('THREAD_NERDIA'),
    'Астерион': os.getenv('THREAD_ASTERION'),
    'Мирноуль': os.getenv('THREAD_MIRNOUL'),
}

API = f'https://api.telegram.org/bot{BOT_TOKEN}'

def post_message(chat_id, text, thread_id=None):
    url = API + '/sendMessage'
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if thread_id:
        try:
            data['message_thread_id'] = int(thread_id)
        except Exception:
            pass
    r = requests.post(url, data=data)
    return r.ok


def process_pending_reports():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''SELECT
                    r.id, r.amount, r.description, r.title, r.report_type,
                    r.author_name, r.recipient_name, r.nickname,
                    k.name as kingdom
                FROM reports r
                LEFT JOIN kingdoms k ON r.kingdom_id=k.id
                WHERE posted=0''')
    rows = c.fetchall()
    for r in rows:
        title = r['title'] or 'Без заголовка'
        report_type = r['report_type'] or 'Другое'
        author = r['author_name'] or 'Не указано'
        recipient = r['recipient_name'] or 'Не указано'
        nickname = f"\\n👤 <i>{r['nickname']}</i>" if r['nickname'] else ''
        amount_text = f"\\n💰 <b>Сумма:</b> {r['amount']}" if r['amount'] not in (None, '', 0) else ''
        
        # Format description with line breaks for better readability
        description = r['description'] or 'Нет описания'
        
        text = (
            f"📌 <b>Новый отчёт</b>\\n\\n"
            f"🏰 <b>Королевство:</b> {r['kingdom'] or 'Империя'}\\n"
            f"🧾 <b>Тип:</b> {report_type}\\n"
            f"📝 <b>Заголовок:</b> {title}\\n"
            f"👤 <b>От кого:</b> {author}{nickname}\\n"
            f"🎯 <b>Кому:</b> {recipient}{amount_text}\\n\\n"
            f"💬 <b>Подробности:</b>\\n{description}"
        )
        thread = THREAD_MAP.get(r['kingdom'])
        ok = post_message(CHAT_ID, text, thread_id=thread)
        if ok:
            c.execute('UPDATE reports SET posted=1 WHERE id=?', (r['id'],))
            conn.commit()
            print(f'Posted report {r["id"]}')
        else:
            print(f'Failed to post report {r["id"]}')
    conn.close()


def poll_and_post():
    while True:
        process_pending_reports()
        time.sleep(15)

if __name__=='__main__':
    if not BOT_TOKEN or not CHAT_ID:
        print('Please set BOT_TOKEN and CHAT_ID in .env')
        exit(1)
    print('Starting telegram poster...')
    poll_and_post()