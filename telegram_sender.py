"""
Отправка сообщений в Telegram (сводный отчёт и тестовое сообщение).
"""
import logging
from datetime import date
from typing import Optional

import requests

from config import (
    get_telegram_admin_id,
    get_telegram_chat_id,
    get_telegram_token,
    get_telegram_topic_id,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot"


def send_message(text: str, parse_mode: str = "HTML", chat_id: Optional[str] = None) -> bool:
    """Отправляет сообщение в чат (опционально в указанный топик). Возвращает True при успехе.

    Args:
        text: Текст сообщения
        parse_mode: Режим форматирования (HTML, Markdown, None). По умолчанию HTML
        chat_id: ID чата для отправки (если None, используется TELEGRAM_CHAT_ID из конфига)
    """
    token = get_telegram_token()
    if chat_id is None:
        chat_id = get_telegram_chat_id()
    chat_id = chat_id.strip()
    url = f"{TELEGRAM_API}{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    topic_id = get_telegram_topic_id()
    # Топик имеет смысл только для целевого группового чата.
    if topic_id is not None and chat_id == get_telegram_chat_id().strip():
        payload["message_thread_id"] = topic_id
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed (%s)", type(e).__name__)
        return False


def test_send() -> bool:
    """
    Ручная отправка тестового отчёта в целевую группу.
    Можно вызывать из main при аргументе командной строки или по необходимости.
    """
    from report_builder import build_report
    from report_delivery import send_followup_reports

    report = build_report()
    text = report.text
    if not text:
        text = "📊 Тестовый отчёт\n\nДанные не получены. Проверьте логи и настройки Adapty."
    if not send_message(text):
        return False
    send_followup_reports(report.report_date)
    return True


def send_ab_report_once(report_date: Optional[date] = None) -> bool:
    """Build and send exactly one validated A/B report to the production target."""
    from ab_test_report import build_ab_test_report

    try:
        text = build_ab_test_report(report_date=report_date)
    except Exception as err:
        logger.error("A/B report build failed (%s)", type(err).__name__)
        return False
    if not text:
        logger.error("A/B report is disabled or empty")
        return False
    return send_message(text)


def build_report_text_for_test() -> str:
    from report_builder import build_report_text

    return build_report_text()
