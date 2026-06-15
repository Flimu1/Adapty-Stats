"""
Отправка дополнительных отчётов после основной ежедневной сводки.
"""
from datetime import date
import logging
from typing import Callable, Optional

from config import get_telegram_admin_id

logger = logging.getLogger(__name__)

ReportBuilder = Callable[[Optional[date]], Optional[str]]


def _notify_admin(report_name: str, err: Exception) -> None:
    admin_id = get_telegram_admin_id()
    if not admin_id:
        return
    from telegram_sender import send_message

    try:
        send_message(
            f"⚠️ Ошибка при отправке {report_name} отчёта: {err}",
            chat_id=admin_id,
        )
    except Exception as send_err:
        logger.exception("Failed to send %s error notification: %s", report_name, send_err)


def _send_optional_report(
    report_name: str,
    builder: ReportBuilder,
    report_date: date,
) -> tuple[bool, Optional[str]]:
    from telegram_sender import send_message

    try:
        text = builder(report_date)
        if not text:
            return False, None
        if send_message(text):
            logger.info("%s report sent successfully", report_name)
            return True, None
        logger.error("Failed to send %s report", report_name)
        return False, f"{report_name} send failed"
    except Exception as err:
        logger.exception("%s report failed: %s", report_name, err)
        _notify_admin(report_name, err)
        return False, str(err)


def send_followup_reports(report_date: date) -> tuple[list[str], list[str]]:
    """Отправляет дополнительные отчёты после основной сводки: A/B, затем Apple Ads."""
    from ab_test_report import build_ab_test_report
    from apple_ads_report import build_apple_ads_report

    sent: list[str] = []
    errors: list[str] = []
    for report_name, builder in (
        ("A/B", build_ab_test_report),
        ("Apple Ads", build_apple_ads_report),
    ):
        was_sent, err = _send_optional_report(report_name, builder, report_date)
        if was_sent:
            sent.append(report_name)
        if err:
            errors.append(f"{report_name}: {err}")
    return sent, errors
