"""
Отправка сообщений в Telegram (сводный отчёт и тестовое сообщение).
"""
import logging
from typing import Optional

import requests

from config import get_telegram_chat_id, get_telegram_token

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot"


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Отправляет сообщение в чат. Возвращает True при успехе."""
    token = get_telegram_token()
    chat_id = get_telegram_chat_id()
    url = f"{TELEGRAM_API}{token}/sendMessage"
    payload = {
        "chat_id": chat_id.strip(),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.exception("Telegram send failed: %s", e)
        return False


def test_send() -> bool:
    """
    Ручная отправка тестового отчёта (без запроса к Adapty).
    Можно вызывать из main при аргументе командной строки или по необходимости.
    """
    from report_builder import build_report_text
    text = build_report_text()
    if not text:
        text = "📊 Тестовый отчёт\n\nДанные не получены. Проверьте логи и настройки Adapty."
    return send_message(text)
