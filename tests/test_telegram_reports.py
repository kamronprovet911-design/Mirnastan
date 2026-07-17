import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import telegram_bot


class TelegramReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.original_db = telegram_bot.DB
        telegram_bot.DB = self.temp_db.name
        self.conn = sqlite3.connect(self.temp_db.name)
        self.conn.execute('CREATE TABLE IF NOT EXISTS kingdoms (id INTEGER PRIMARY KEY, name TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, kingdom_id INTEGER, report_type TEXT, amount REAL, title TEXT, description TEXT, author_name TEXT, recipient_name TEXT, nickname TEXT, posted INTEGER DEFAULT 0)')
        self.conn.execute("INSERT INTO reports (kingdom_id, report_type, amount, title, description, author_name, recipient_name, nickname) VALUES (NULL, 'Расход на народ', -500, 'Трата на народ', 'Для жителей', 'Император', 'Народ', 'Казна')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.temp_db.name)
        telegram_bot.DB = self.original_db

    def test_pending_report_without_kingdom_is_marked_posted(self):
        with patch('telegram_bot.post_message', return_value=True):
            telegram_bot.process_pending_reports()
        row = self.conn.execute("SELECT posted FROM reports WHERE id=1").fetchone()
        self.assertEqual(row[0], 1)


if __name__ == '__main__':
    unittest.main()
