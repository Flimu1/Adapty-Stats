"""
Загрузка настроек из переменных окружения (.env локально / Railway UI в проде).
Поддерживается любое количество приложений: APP1, APP2, APP3, ...
"""
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class AppConfig:
    """Один проект Adapty: ключ API и отображаемое имя."""
    api_key: str
    name: str


def _get_apps_from_env() -> list[AppConfig]:
    """Собирает список приложений по переменным ADAPTY_API_KEY_APP1, APP2, ..."""
    apps: list[AppConfig] = []
    n = 1
    while True:
        key = os.getenv(f"ADAPTY_API_KEY_APP{n}")
        name = os.getenv(f"ADAPTY_APP_NAME_{n}", "").strip() or f"App {n}"
        if not key or not key.strip():
            break
        apps.append(AppConfig(api_key=key.strip(), name=name or f"App {n}"))
        n += 1
    return apps


def get_telegram_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в окружении")
    return token


def get_telegram_chat_id() -> str:
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID не задан в окружении")
    return chat_id


def get_adapty_apps() -> list[AppConfig]:
    apps = _get_apps_from_env()
    if not apps:
        raise ValueError(
            "Не найдено ни одного приложения. Задайте ADAPTY_API_KEY_APP1 и ADAPTY_APP_NAME_1 (и при необходимости APP2, ...)"
        )
    return apps


def get_adapty_base_url() -> str:
    """Базовый URL Adapty Export Analytics API (api-admin.adapty.io)."""
    return os.getenv(
        "ADAPTY_API_BASE_URL", "https://api-admin.adapty.io"
    ).rstrip("/")


def get_adapty_analytics_path() -> str:
    """Путь к эндпоинту Retrieve analytics data."""
    return os.getenv(
        "ADAPTY_ANALYTICS_PATH", "api/v1/client-api/metrics/analytics/"
    ).strip().lstrip("/")


def get_timezone() -> str:
    return os.getenv("TZ", "Europe/Minsk")


def get_report_time() -> str:
    """Время отправки отчёта (часы:минуты), например '09:00'."""
    return os.getenv("REPORT_TIME", "09:00")


def get_report_hour_minute() -> tuple[int, int]:
    """(hour, minute) по местному времени для планировщика."""
    raw = get_report_time()
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw.strip())
    if not m:
        return 9, 0
    return int(m.group(1)), int(m.group(2))
