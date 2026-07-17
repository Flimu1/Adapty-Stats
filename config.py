"""
Загрузка настроек из переменных окружения (.env локально / Railway UI в проде).
Поддерживается любое количество приложений: APP1, APP2, APP3, ...
"""
import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

MINSK_TIMEZONE = "Europe/Minsk"


@dataclass
class AppConfig:
    """Один проект Adapty: ключ API и отображаемое имя."""
    api_key: str
    name: str
    is_visible: bool = True


def _get_apps_from_env() -> list[AppConfig]:
    """Собирает список приложений по переменным ADAPTY_API_KEY_APP1, APP2, ..."""
    apps: list[AppConfig] = []
    n = 1
    while True:
        key = os.getenv(f"ADAPTY_API_KEY_APP{n}")
        name = os.getenv(f"ADAPTY_APP_NAME_{n}", "").strip() or f"App {n}"
        if not key or not key.strip():
            break
        visible_raw = os.getenv(f"ADAPTY_APP_VISIBLE_{n}", "true").strip().lower()
        is_visible = visible_raw != "false"
        apps.append(AppConfig(api_key=key.strip(), name=name or f"App {n}", is_visible=is_visible))
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


def get_telegram_admin_id() -> Optional[str]:
    """
    Telegram user ID того, кто может управлять ботом из лички.
    Если задан — команды (/start, Собрать данные, время) принимаются только из личного чата с этим пользователем;
    отчёты по-прежнему уходят в группу (TELEGRAM_CHAT_ID), в группе никто не видит ваших команд.
    Как получить: напишите боту в личку, затем откройте getUpdates — в message.from.id будет ваш user id.
    """
    raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
    return raw if raw else None


def get_telegram_topic_id() -> Optional[int]:
    """
    ID топика (темы) в группе с включёнными топиками.
    Если задан — отчёт отправляется в этот топик (message_thread_id).
    Как получить: отправьте в нужный топик любое сообщение и посмотрите getUpdates — в сообщении будет message_thread_id.
    """
    raw = os.getenv("TELEGRAM_TOPIC_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


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


def get_adapty_conversion_path() -> str:
    """Путь к эндпоинту Retrieve conversion data (Install → Paid и др.)."""
    return os.getenv(
        "ADAPTY_CONVERSION_PATH", "api/v1/client-api/metrics/conversion/"
    ).strip().lstrip("/")


def get_adapty_cohort_path() -> str:
    """Путь к эндпоинту Retrieve cohort data."""
    return os.getenv(
        "ADAPTY_COHORT_PATH", "api/v1/client-api/metrics/cohort/"
    ).strip().lstrip("/")


def get_adapty_funnel_path() -> str:
    """Путь к эндпоинту Retrieve funnel data."""
    return os.getenv(
        "ADAPTY_FUNNEL_PATH", "api/v1/client-api/metrics/funnel/"
    ).strip().lstrip("/")


def is_ab_test_report_enabled() -> bool:
    """Включён ли отдельный Telegram-отчёт по A/B-тесту."""
    raw = os.getenv("AB_TEST_REPORT_ENABLED", "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_ab_test_app_index() -> int:
    """Номер приложения из ADAPTY_API_KEY_APP{N}, для которого строить A/B-отчёт."""
    raw = os.getenv("AB_TEST_APP_INDEX", "1").strip()
    try:
        idx = int(raw)
    except ValueError:
        raise ValueError("AB_TEST_APP_INDEX должен быть целым числом")
    if idx < 1:
        raise ValueError("AB_TEST_APP_INDEX должен быть >= 1")
    return idx


def get_ab_test_name() -> str:
    return os.getenv("AB_TEST_NAME", "").strip()


def get_ab_test_id() -> str:
    """Immutable Adapty dashboard ID of the A/B test."""
    return os.getenv("AB_TEST_ID", "").strip()


def get_ab_test_start_date() -> str:
    return os.getenv("AB_TEST_START_DATE", "").strip()


def get_ab_test_variant_value(variant: str, field: str) -> str:
    """Читает AB_TEST_VARIANT_{A/B}_{LABEL/PAYWALL_ID/PAYWALL_NAME}."""
    key = f"AB_TEST_VARIANT_{variant.upper()}_{field.upper()}"
    return os.getenv(key, "").strip()


def is_apple_ads_report_enabled() -> bool:
    """Включён ли отдельный Telegram-отчёт по Apple Ads."""
    raw = os.getenv("APPLE_ADS_REPORT_ENABLED", "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_apple_ads_app_index() -> int:
    """Номер приложения из ADAPTY_API_KEY_APP{N}, для которого строить Apple Ads отчёт."""
    raw = os.getenv("APPLE_ADS_APP_INDEX", "1").strip()
    try:
        idx = int(raw)
    except ValueError:
        raise ValueError("APPLE_ADS_APP_INDEX должен быть целым числом")
    if idx < 1:
        raise ValueError("APPLE_ADS_APP_INDEX должен быть >= 1")
    return idx


def get_apple_ads_report_title() -> str:
    return os.getenv("APPLE_ADS_REPORT_TITLE", "Unfollowers").strip() or "Unfollowers"


def get_apple_ads_start_date() -> str:
    return os.getenv("APPLE_ADS_START_DATE", "").strip()


def get_apple_ads_attribution_source() -> str:
    return os.getenv("APPLE_ADS_ATTRIBUTION_SOURCE", "apple_search_ads").strip()


def get_adapty_asa_api_base_url() -> str:
    return os.getenv(
        "ADAPTY_ASA_API_BASE_URL",
        "https://api-asa-admin.adapty.io/api/v1",
    ).rstrip("/")


def get_adapty_dashboard_token() -> str:
    return (
        os.getenv("ADAPTY_DASHBOARD_TOKEN", "").strip()
        or os.getenv("ADAPTY_ASA_AUTH_TOKEN", "").strip()
    )


def get_adapty_dashboard_company_id() -> str:
    return os.getenv("ADAPTY_DASHBOARD_COMPANY_ID", "").strip()


def get_adapty_dashboard_app_id() -> str:
    return os.getenv("ADAPTY_DASHBOARD_APP_ID", "").strip()


def get_apple_ads_internal_app_id() -> str:
    return os.getenv("APPLE_ADS_INTERNAL_APP_ID", "").strip()


def get_apple_ads_metrics_paths() -> list[str]:
    """
    Возможные пути к Adapty Ads Manager metrics endpoint.
    Публичный Analytics Export API документирует attribution-фильтры, но spend
    живёт в Apple Ads Manager, поэтому путь оставлен настраиваемым.
    """
    raw = os.getenv("APPLE_ADS_METRICS_PATH", "").strip()
    if raw:
        return [p.strip().lstrip("/") for p in raw.split(",") if p.strip()]
    return [
        "api/v1/client-api/ads-manager/metrics/analytics/",
        "api/v1/client-api/apple-ads/metrics/analytics/",
    ]


def get_apple_ads_api_base_url() -> str:
    return os.getenv(
        "APPLE_ADS_API_BASE_URL",
        "https://api.searchads.apple.com/api/v5",
    ).rstrip("/")


def get_apple_ads_client_id() -> str:
    return os.getenv("APPLE_ADS_CLIENT_ID", "").strip()


def get_apple_ads_team_id() -> str:
    return os.getenv("APPLE_ADS_TEAM_ID", "").strip()


def get_apple_ads_key_id() -> str:
    return os.getenv("APPLE_ADS_KEY_ID", "").strip()


def get_apple_ads_private_key() -> str:
    return os.getenv("APPLE_ADS_PRIVATE_KEY", "").strip().replace("\\n", "\n")


def get_apple_ads_org_id() -> str:
    return os.getenv("APPLE_ADS_ORG_ID", "").strip()


def get_apple_ads_adam_id() -> str:
    """Опциональный App Store app id для фильтрации Apple Ads campaign report по приложению."""
    return os.getenv("APPLE_ADS_ADAM_ID", "").strip()


def get_timezone() -> str:
    """
    Единая таймзона проекта: Europe/Minsk.
    Используется планировщиком и общими датами отчёта.
    """
    return MINSK_TIMEZONE


def get_adapty_timezone() -> str:
    """
    Таймзона для запросов к Adapty Analytics (заголовок Adapty-Tz и границы дат).
    Зафиксирована как Europe/Minsk для совпадения API и внутренних расчётов.
    """
    return MINSK_TIMEZONE


# Файл для хранения времени сбора (локальный override, если REPORT_TIME не задан)
_REPORT_TIME_FILE = os.path.join(os.path.dirname(__file__), "data", "report_time.txt")


def _read_report_time_from_file() -> Optional[str]:
    """Читает время из файла, если файл есть и не пустой."""
    try:
        if os.path.isfile(_REPORT_TIME_FILE):
            with open(_REPORT_TIME_FILE, "r", encoding="utf-8") as f:
                s = f.read().strip()
            if s and re.match(r"^\d{1,2}:\d{2}$", s):
                return s
    except OSError:
        pass
    return None


def get_report_time() -> str:
    """Время отправки отчёта (часы:минуты), например '09:00'."""
    from_env = os.getenv("REPORT_TIME", "").strip()
    if from_env:
        return from_env
    from_file = _read_report_time_from_file()
    if from_file is not None:
        return from_file
    return "09:00"


def set_report_time(time_str: str) -> tuple[bool, str]:
    """
    Сохраняет время в файл. time_str в формате ЧЧ:ММ (например 09:30).
    Возвращает (успех, сообщение_об_ошибке).
    """
    time_str = time_str.strip()
    if not re.match(r"^(\d{1,2}):(\d{2})$", time_str):
        return False, "Неверный формат. Используйте ЧЧ:ММ (например, 09:00)."
    h, m = int(time_str.split(":")[0]), int(time_str.split(":")[1])
    if h < 0 or h > 23 or m < 0 or m > 59:
        return False, "Час должен быть 0–23, минуты 0–59."
    try:
        os.makedirs(os.path.dirname(_REPORT_TIME_FILE), exist_ok=True)
        with open(_REPORT_TIME_FILE, "w", encoding="utf-8") as f:
            f.write(time_str)
        return True, ""
    except OSError as e:
        return False, f"Не удалось сохранить: {e}"


def get_report_hour_minute() -> tuple[int, int]:
    """(hour, minute) по местному времени для планировщика."""
    raw = get_report_time()
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw.strip())
    if not m:
        return 9, 0
    return int(m.group(1)), int(m.group(2))
