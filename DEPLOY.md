# Боцит - Империя и Финансы

Веб-приложение для управления бюджетом вымышленной империи с Telegram интеграцией.

## Деплой на Render (бесплатно)

### Шаг 1: Подготовка репозитория

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
git push -u origin main
```

### Шаг 2: Создание сервиса на Render

1. Перейдите на [render.com](https://render.com)
2. Нажмите **New +** → **Web Service**
3. Выберите **Deploy an existing Git repository**
4. Вставьте URL вашего GitHub репозитория
5. Настройте:
   - **Name**: botsite (или другое имя)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
6. Нажмите **Deploy**

### Шаг 3: Переменные окружения (если нужны)

Если используете Telegram бота, добавьте переменные в Render:
- Перейдите в **Environment** → **Add Environment Variable**
- Добавьте `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` и т.д.

### Шаг 4: Готово!

Приложение будет доступно по URL вида `https://botsite-xxxxx.onrender.com`

## Локальный запуск

```bash
pip install -r requirements.txt
python app.py
```

Откройте http://127.0.0.1:5000 в браузере.

## Учётные данные

**Император**: `emperor` / `emperor_pass`
**Король Нердии**: `king_nerdia` / `king_nerdia_pass`
**Граф Нердии**: `graf_nerdia_1` / `graf_nerdia_1_pass`

И т.д. для других королевств.

## Возможности

- Управление бюджетом королевств
- Расходы на народ
- Переводы между королевствами
- Система отчётов
- Telegram интеграция
- Ролевой контроль доступа
