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
        kingdom = r['kingdom'] or 'Империя'
        
        # Формируем красивый заголовок в зависимости от типа отчета
        if report_type == 'Ресурсный доход':
            header_emoji = '📢'
            header_text = 'НОВОЕ НАЗНАЧЕНИЕ ОТ ИМПЕРАТОРА'
            details_label = 'Утвержденные ресурсы (в неделю):'
            
            # Парсим описание для красивого вывода ресурсов
            desc_text = r['description'] or 'Нет описания'
            formatted_desc = f"Назначен постоянный ресурсный доход для развития земель.\n\n{details_label}"
            
            # Пытаемся выделить цифры из описания для красивого формата
            if 'дерево=' in desc_text or 'металл=' in desc_text or 'продовольствие=' in desc_text:
                parts = []
                if 'дерево=' in desc_text:
                    val = desc_text.split('дерево=')[1].split(',')[0].replace('0.0', '0').strip()
                    parts.append(f"🌲 Дерево: <b>{val}</b>")
                if 'металл=' in desc_text:
                    val = desc_text.split('металл=')[1].split(',')[0].replace('0.0', '0').strip()
                    parts.append(f"⛓️ Металл: <b>{val}</b>")
                if 'продовольствие=' in desc_text:
                    val = desc_text.split('продовольствие=')[1].split('.')[0].strip()
                    parts.append(f"🍞 Продовольствие: <b>{val}</b>")
                if parts:
                    formatted_desc += "\n" + "\n".join(parts)
                formatted_desc += "\n\n✅ <i>Указ вступил в силу.</i>"
            else:
                formatted_desc += f"\n{desc_text}"
                
        elif report_type == 'Выплата сюзереном':
            header_emoji = '💰'
            header_text = 'ВЫПЛАТА ОТ СЮЗЕРЕНА'
            formatted_desc = f"Поступило финансирование из казны сюзерена.\n\n💵 <b>Сумма:</b> {r['amount']}\n✅ <i>Средства зачислены.</i>"
            
        elif report_type == 'Постройка':
            header_emoji = '🏗️'
            header_text = 'СТАТУС ПОСТРОЙКИ'
            formatted_desc = f"{r['description'] or 'Обновление статуса постройки'}"
            
        else:
            header_emoji = '📌'
            header_text = 'НОВЫЙ ОТЧЁТ'
            formatted_desc = r['description'] or 'Нет описания'

        # Собираем основное сообщение
        text = (
            f"{header_emoji} <b>{header_text}</b>\n\n"
            f"🏰 <b>Королевство:</b> {kingdom}\n"
            f"👤 <b>Инициатор:</b> {author}\n"
        )
        
        if r['nickname']:
            text += f"📝 <i>({r['nickname']})</i>\n"
            
        if r['amount'] and r['amount'] not in ('', 0, None) and report_type != 'Ресурсный доход':
            text += f"💰 <b>Сумма:</b> {r['amount']}\n"
            
        text += f"\n📜 <b>Подробности:</b>\n{formatted_desc}"

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