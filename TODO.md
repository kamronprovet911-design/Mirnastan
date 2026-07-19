# TODO — Ресурсы (Д/М/П), постройки, заявки, герцогства, отчёты

## Этап 0 — Подготовка
- [x] Уточнили контракт постройки: королевство платит деньгами из `kingdoms.budget`, казна покрывает из `settings.treasury`, ресурсы списываются из балансов `kingdoms.tree/metal/food`, доход ресурсов после approve увеличивается на величины, заданные императором.

## Этап 1 — Миграции БД
- [x] Обновить `app.py` функции `ensure_runtime_tables/ensure_runtime_schema`:
  - добавлены колонки в `kingdoms`: `tree`, `metal`, `food`, `tree_income`, `metal_income`, `food_income`
  - добавлена таблица `building_requests`.
- [x] Обновить `db_init.py` чтобы миграции работали на пустой базе.

## Этап 2 — Ресурсная логика
- [x] Добавить функцию `apply_configured_daily_resource_income(...)`
- [x] Добавить функции:
  - [x] `apply_resource_transfer_between_kingdoms(...)`
  - [x] `submit_building_request(...)`
  - [x] `approve_building_request(...)`
- [x] В ежедневном цикле вызывать раздачу ресурсов + вставлять report.

## Этап 3 — Роуты и UI
- [x] Добавить роуты:
  - [x] `POST /resources/transfer`
  - [x] `GET /resources`
  - [x] `POST /build_requests/submit`
  - [x] `POST /build_requests/approve`
  - [x] `GET /build_requests`
- [x] Добавить шаблоны:
  - [x] `templates/resources.html`
  - [x] `templates/build_requests.html`
- [x] Обновить меню: `templates/dashboard.html`.

## Этап 4 — Отчётность
- [x] На каждое действие (submit/approve/transfer) вставлять `insert_report(...)`.
- [x] После каждого POST вызывать `send_report_to_telegram()`.

## Этап 5 — Права и пароли
- [ ] Добавить отчётность для смены пароля:
  - король→графам
  - император→королям
- [ ] Проверить, что король видит/может управлять всеми своими графствами (UI фильтрация).

## Этап 6 — Герцогства (минимум)
- [ ] Добавить таблицу `duchies`.
- [ ] Добавить роут/форма: король создаёт герцогство.
- [ ] Добавить report на создание.

## Этап 7 — Тесты
- [ ] Добавить тесты `tests/test_resources_mechanics.py`:
  - перевод ресурсов
  - submit/approve постройки (проверка списаний и увеличения income)
  - отчётность создаётся.

## Этап 8 — Проверка
- [ ] Запустить тесты: `python -m unittest`.

