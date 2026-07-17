import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app as app_module


class FinanceMechanicsTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        app_module.DB_PATH = self.temp_db.name
        self.conn = sqlite3.connect(self.temp_db.name)
        self.conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT UNIQUE, value TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS kingdoms (id INTEGER PRIMARY KEY, name TEXT UNIQUE, budget REAL DEFAULT 0)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, from_user INTEGER, to_kingdom INTEGER, amount REAL, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, kingdom_id INTEGER, report_type TEXT, amount REAL, title TEXT, description TEXT, author_name TEXT, recipient_name TEXT, nickname TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, posted INTEGER DEFAULT 0)')
        self.conn.execute("INSERT INTO settings (key, value) VALUES ('treasury', '10000')")
        self.conn.execute("INSERT INTO kingdoms (name, budget) VALUES ('Нердия', 5000)")
        self.conn.execute("INSERT INTO kingdoms (name, budget) VALUES ('Астерион', 3000)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.unlink(self.temp_db.name)

    def test_role_access_for_money_actions(self):
        self.assertTrue(app_module.role_can_manage_money('emperor'))
        self.assertTrue(app_module.role_can_manage_money('king'))
        self.assertTrue(app_module.role_can_manage_money('graf'))
        self.assertFalse(app_module.role_can_manage_money('user'))

    def test_people_expense_reduces_treasury_and_records_report(self):
        app_module.apply_people_expense(self.conn, 1500, 'Покупки для народа')
        self.conn.commit()
        treasury = self.conn.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()[0]
        report = self.conn.execute("SELECT report_type, amount, title, description FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(float(treasury), 8500.0)
        self.assertEqual(report[0], 'Расход на народ')
        self.assertEqual(report[1], -1500.0)

    def test_transfer_between_kingdoms_updates_balances(self):
        app_module.apply_transfer_between_kingdoms(self.conn, 1, 2, 1200, 'Перевод для нужд')
        self.conn.commit()
        source_budget = self.conn.execute("SELECT budget FROM kingdoms WHERE id=1").fetchone()[0]
        target_budget = self.conn.execute("SELECT budget FROM kingdoms WHERE id=2").fetchone()[0]
        report = self.conn.execute("SELECT report_type, amount FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(float(source_budget), 3800.0)
        self.assertEqual(float(target_budget), 4200.0)
        self.assertEqual(report[0], 'Перевод')
        self.assertEqual(float(report[1]), 1200.0)


if __name__ == '__main__':
    unittest.main()
