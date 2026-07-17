import os
import sys
sys.path.insert(0, os.getcwd())
import app as app_module

client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess['user'] = {'username': 'king_nerdia', 'role': 'king'}

resp = client.get('/submit_report')
print('status', resp.status_code)
html = resp.get_data(as_text=True)
print('contains author value', 'value="Король Нердия"' in html)
print('contains kingdom option', 'Нердия' in html)
print(html[html.find('name="author_name"')-200:html.find('name="author_name"')+500] if 'name="author_name"' in html else 'author_name field not found')
