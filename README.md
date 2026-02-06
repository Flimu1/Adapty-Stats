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

## Деплой на Railway

1. Создайте проект на [Railway](https://railway.app) и подключите этот репозиторий (GitHub).

2. В настройках сервиса задайте **переменные окружения** (Variables) — те же, что в `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `ADAPTY_API_KEY_APP1`, `ADAPTY_APP_NAME_1`
   - `ADAPTY_API_KEY_APP2`, `ADAPTY_APP_NAME_2`
   - При необходимости: `TZ`, `REPORT_TIME`, `ADAPTY_API_BASE_URL`, `ADAPTY_EXPORT_PATH`

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

Если реальный эндпоинт или формат ответа отличаются от заложенных в коде, задайте в env:
- `ADAPTY_API_BASE_URL` — базовый URL API
- `ADAPTY_EXPORT_PATH` — путь к Export Analytics (по умолчанию `v1/export/analytics`)

Структуру ответа можно адаптировать в `adapty_client.py` в функции `_parse_analytics_response`.
