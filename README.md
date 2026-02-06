# Adapty Daily Report Bot

Telegram-бот для ежедневной отчётности по метрикам Adapty (MRR, Installs). Хостинг: Railway.

## Репозиторий на GitHub

Локально уже выполнены `git init`, первый коммит и все файлы готовы к push.

**Если установлен GitHub CLI:**
```bash
cd "Adapty stats"
gh repo create adapty-stats --private --source=. --remote=origin --push
```
(Или `--public`, имя репозитория по желанию.)

**Если репозиторий создаёте вручную на GitHub:**
1. На [github.com/new](https://github.com/new) создайте репозиторий (например `adapty-stats`), без README.
2. Выполните в каталоге проекта:
   ```bash
   git remote add origin https://github.com/<ВАШ_USERNAME>/adapty-stats.git
   git push -u origin main
   ```

## Локальный запуск

1. Клонировать репозиторий и перейти в каталог:
   ```bash
   git clone <repo-url> && cd "Adapty stats"
   ```

2. Создать виртуальное окружение и установить зависимости:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Скопировать `.env.example` в `.env` и заполнить переменные (токен бота, Chat ID, ключи Adapty, имена приложений).

4. Проверка конфига и тестовая отправка:
   ```bash
   python main.py --health
   python main.py --test-send
   ```

5. Запуск планировщика (ежедневный отчёт в 09:00 Europe/Minsk):
   ```bash
   python main.py
   ```

## Ручной сбор данных (кнопка в боте)

Пока работает планировщик, бот слушает чат. В том же чате, куда приходит ежедневный отчёт:

- **Команды:** `/start` — приветствие и кнопка; `/collect` или `/data` — сразу собрать актуальные данные с Adapty и отправить отчёт.
- **Кнопка:** при `/start` появляется inline-кнопка **📊 Collect Data**. Нажатие запускает сбор данных с Adapty и отправку отчёта в чат.

Ответы бота приходят только в чат с `TELEGRAM_CHAT_ID` (другие пользователи не могут запускать сбор).

## Деплой на Railway

1. Создайте проект на [Railway](https://railway.app) и подключите этот репозиторий (GitHub).

2. В настройках сервиса задайте **переменные окружения** (Variables) — те же, что в `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `ADAPTY_API_KEY_APP1`, `ADAPTY_APP_NAME_1`
   - `ADAPTY_API_KEY_APP2`, `ADAPTY_APP_NAME_2`
   - При необходимости: `TZ`, `REPORT_TIME`, `ADAPTY_API_BASE_URL`, `ADAPTY_ANALYTICS_PATH`

3. **Procfile** уже настроен: `worker: python main.py`. Railway запустит процесс как worker (без HTTP). Отчёт будет уходить раз в сутки в заданное время.

4. Деплой: при каждом push в ветку по умолчанию Railway соберёт образ и перезапустит worker.

### Health check (опционально)

Сервис не поднимает HTTP-сервер. Проверка конфига локально: `python main.py --health`. На Railway можно не настраивать health check или использовать встроенные проверки процесса.

### Добавление третьего (и более) приложения

Добавьте в переменные окружения:
- `ADAPTY_API_KEY_APP3`, `ADAPTY_APP_NAME_3`
Код подхватит их автоматически.

## Формат отчёта

- Заголовок: 📊 Отчёт на ДД.ММ.ГГГГ  
- По каждому приложению: **Название**, 💰 MRR: $X,XXX (±$YY), 📲 Installs: X,XXX (±ZZ).  
- Parse mode в Telegram: Markdown.

## Adapty API

Используется официальный [Export Analytics API](https://adapty.io/docs/export-analytics-api):
- **Retrieve analytics data** — MRR и Installs
- URL: `https://api-admin.adapty.io/api/v1/client-api/metrics/analytics/`

При необходимости переопределите в env:
- `ADAPTY_API_BASE_URL` — по умолчанию `https://api-admin.adapty.io`
- `ADAPTY_ANALYTICS_PATH` — по умолчанию `api/v1/client-api/metrics/analytics/`
