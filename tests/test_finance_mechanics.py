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
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT UNIQUE, value TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS kingdoms (id INTEGER PRIMARY KEY, name TEXT UNIQUE, budget REAL DEFAULT 0, daily_income REAL DEFAULT 0)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, role TEXT, password_hash TEXT, balance REAL DEFAULT 0, daily_income REAL DEFAULT 0)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, from_user INTEGER, to_kingdom INTEGER, amount REAL, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, kingdom_id INTEGER, report_type TEXT, amount REAL, title TEXT, description TEXT, author_name TEXT, recipient_name TEXT, nickname TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, posted INTEGER DEFAULT 0)')
        self.conn.execute("INSERT INTO settings (key, value) VALUES ('treasury', '10000')")
        self.conn.execute("INSERT INTO settings (key, value) VALUES ('daily_income_last_date', '')")
        self.conn.execute("INSERT INTO users (username, role, balance) VALUES ('king_nerdia', 'king', 2000)")
        self.conn.execute("INSERT INTO users (username, role, balance) VALUES ('peasant_ivan', 'peasant', 800)")
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

    def test_people_expense_uses_user_balance_and_records_report(self):
        app_module.apply_people_expense(self.conn, 1500, 'Покупки для народа', acting_user={'username': 'king_nerdia', 'role': 'king'})
        self.conn.commit()
        treasury = self.conn.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()[0]
        balance = self.conn.execute("SELECT balance FROM users WHERE username='king_nerdia'").fetchone()[0]
        report = self.conn.execute("SELECT report_type, amount, title, description FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(float(treasury), 10000.0)
        self.assertEqual(float(balance), 500.0)
        self.assertEqual(report[0], 'Расход на народ')
        self.assertEqual(report[1], -1500.0)

    def test_peasant_spending_uses_their_own_balance(self):
        app_module.apply_people_expense(self.conn, 400, 'Корм для жителей', acting_user={'username': 'peasant_ivan', 'role': 'peasant'})
        self.conn.commit()
        treasury = self.conn.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()[0]
        balance = self.conn.execute("SELECT balance FROM users WHERE username='peasant_ivan'").fetchone()[0]
        self.assertEqual(float(treasury), 10000.0)
        self.assertEqual(float(balance), 400.0)

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

    def test_configured_daily_income_pays_users_and_kingdoms_once_per_day(self):
        self.conn.execute("UPDATE users SET daily_income=100 WHERE username='king_nerdia'")
        self.conn.execute("UPDATE users SET daily_income=50 WHERE username='peasant_ivan'")
        self.conn.execute("UPDATE kingdoms SET daily_income=300 WHERE id=1")
        self.conn.commit()

        paid = app_module.apply_configured_daily_income(self.conn, '2026-07-17', 'test payout')
        self.conn.commit()

        king_balance = self.conn.execute("SELECT balance FROM users WHERE username='king_nerdia'").fetchone()[0]
        peasant_balance = self.conn.execute("SELECT balance FROM users WHERE username='peasant_ivan'").fetchone()[0]
        kingdom_budget = self.conn.execute('SELECT budget FROM kingdoms WHERE id=1').fetchone()[0]
        treasury = self.conn.execute("SELECT value FROM settings WHERE key='treasury'").fetchone()[0]
        last_date = self.conn.execute("SELECT value FROM settings WHERE key='daily_income_last_date'").fetchone()[0]
        report = self.conn.execute("SELECT report_type, amount FROM reports ORDER BY id DESC LIMIT 1").fetchone()

        self.assertTrue(paid)
        self.assertEqual(float(king_balance), 2100.0)
        self.assertEqual(float(peasant_balance), 850.0)
        self.assertEqual(float(kingdom_budget), 5300.0)
        self.assertEqual(float(treasury), 9550.0)
        self.assertEqual(last_date, '2026-07-17')
        self.assertEqual(report[0], 'Ежедневный доход')
        self.assertEqual(float(report[1]), 450.0)

        paid_again = app_module.apply_configured_daily_income(self.conn, '2026-07-17', 'test payout')
        self.conn.commit()
        king_balance_again = self.conn.execute("SELECT balance FROM users WHERE username='king_nerdia'").fetchone()[0]

        self.assertFalse(paid_again)
        self.assertEqual(float(king_balance_again), 2100.0)

    def test_daily_income_requires_treasury_to_cover_full_payment(self):
        self.conn.execute("UPDATE settings SET value='100' WHERE key='treasury'")
        self.conn.execute("UPDATE users SET daily_income=100 WHERE username='king_nerdia'")
        self.conn.execute("UPDATE kingdoms SET daily_income=300 WHERE id=1")
        self.conn.commit()

        paid = app_module.apply_configured_daily_income(self.conn, '2026-07-17', 'test payout')
        self.conn.commit()

        king_balance = self.conn.execute("SELECT balance FROM users WHERE username='king_nerdia'").fetchone()[0]
        kingdom_budget = self.conn.execute('SELECT budget FROM kingdoms WHERE id=1').fetchone()[0]
        last_date = self.conn.execute("SELECT value FROM settings WHERE key='daily_income_last_date'").fetchone()[0]

        self.assertFalse(paid)
        self.assertEqual(float(king_balance), 2000.0)
        self.assertEqual(float(kingdom_budget), 5000.0)
        self.assertEqual(last_date, '')

    def test_emperor_can_assign_daily_income_to_user_and_kingdom(self):
        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = {'username': 'emperor', 'role': 'emperor', 'balance': 0}

            user_response = client.post('/daily_income', data={
                'target_type': 'user',
                'user_id': '1',
                'amount': '75',
            })
            kingdom_response = client.post('/daily_income', data={
                'target_type': 'kingdom',
                'kingdom_id': '1',
                'amount': '250',
            })

        user_income = self.conn.execute("SELECT daily_income FROM users WHERE username='king_nerdia'").fetchone()[0]
        kingdom_income = self.conn.execute('SELECT daily_income FROM kingdoms WHERE id=1').fetchone()[0]

        self.assertEqual(user_response.status_code, 302)
        self.assertEqual(kingdom_response.status_code, 302)
        self.assertEqual(float(user_income), 75.0)
        self.assertEqual(float(kingdom_income), 250.0)

    def test_register_and_login_create_schema_on_empty_database(self):
        empty_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        empty_db_path = empty_db.name
        empty_db.close()
        os.unlink(empty_db_path)
        previous_db_path = app_module.DB_PATH
        app_module.DB_PATH = empty_db_path
        app_module.app.config['TESTING'] = True
        try:
            with app_module.app.test_client() as client:
                register_response = client.post('/register', data={
                    'username': 'render_user',
                    'password': 'render_pass',
                    'role': 'peasant',
                })
                login_response = client.post('/login', data={
                    'username': 'render_user',
                    'password': 'render_pass',
                })

            conn = sqlite3.connect(empty_db_path)
            try:
                user_count = conn.execute("SELECT COUNT(*) FROM users WHERE username='render_user'").fetchone()[0]
                emperor_count = conn.execute("SELECT COUNT(*) FROM users WHERE username='emperor'").fetchone()[0]
                kingdom_count = conn.execute('SELECT COUNT(*) FROM kingdoms').fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(register_response.status_code, 302)
            self.assertEqual(login_response.status_code, 302)
            self.assertEqual(user_count, 1)
            self.assertEqual(emperor_count, 1)
            self.assertGreaterEqual(kingdom_count, 3)
        finally:
            app_module.DB_PATH = previous_db_path
            if os.path.exists(empty_db_path):
                os.unlink(empty_db_path)


if __name__ == '__main__':
    unittest.main()
