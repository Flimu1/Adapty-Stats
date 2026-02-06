# Структура проекта — Adapty Daily Report Bot

## Список файлов с описанием

| Файл / папка | Описание |
|--------------|----------|
| **Корень проекта** | |
| `README.md` | Инструкция по установке, настройке и деплою на Railway |
| `requirements.txt` | Зависимости Python (requests, python-dotenv, apscheduler и др.) |
| `.env.example` | Шаблон переменных окружения с комментариями (копировать в `.env` локально) |
| `Procfile` | Команда запуска для Railway (например: `web: python main.py`) |
| `runtime.txt` | Версия Python для Railway (например: `python-3.11.x`) |
| `main.py` | Точка входа: инициализация, планировщик APScheduler, запуск воркера |
| **Модули приложения** | |
| `config.py` | Загрузка настроек из переменных окружения (.env / Railway), валидация |
| `adapty_client.py` | Клиент к Adapty Analytics Export API: запросы MRR и Installs по приложениям |
| `telegram_sender.py` | Отправка сообщений в Telegram (сводный отчёт, тестовое сообщение) |
| `report_builder.py` | Сбор данных по всем приложениям, расчёт дельт за 24ч, форматирование текста отчёта |
| `scheduler.py` | Настройка APScheduler: ежедневная задача в 09:00 Europe/Minsk |
| **Документация и конфиг** | |
| `docs/PROJECT_STRUCTURE.md` | Этот файл — список файлов и краткое описание |
| `docs/ARCHITECTURE.md` | Схема работы: от планировщика до Telegram |
| `docs/DATA_CHECKLIST.md` | Чек-лист данных для подготовки (токены, Chat ID, эндпоинты Adapty) |

## Зависимости (requirements.txt)

- **requests** — HTTP-запросы к Adapty API
- **python-dotenv** — загрузка `.env` локально (на Railway не используется)
- **apscheduler** — ежедневная отправка отчёта без cron
- Стандартная библиотека: **concurrent.futures** (асинхронные запросы к API), **logging**

Дополнительные пакеты при необходимости (например, для health check): по желанию.
