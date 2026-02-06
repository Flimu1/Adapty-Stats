"""
Настройка APScheduler: ежедневная отправка отчёта в 09:00 Europe/Minsk.
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_report_hour_minute, get_timezone

logger = logging.getLogger(__name__)


def _send_daily_job() -> None:
    """Job для планировщика: собрать отчёт и отправить в Telegram."""
    from report_builder import build_report_text
    from telegram_sender import send_message
    try:
        text = build_report_text()
        if send_message(text):
            logger.info("Daily report sent successfully")
        else:
            logger.error("Failed to send daily report")
    except Exception as e:
        logger.exception("Daily report job failed: %s", e)


def run_scheduler() -> None:
    """Запускает блокирующий планировщик с одной задачей в 09:00 по местному времени."""
    from telegram_bot import start_bot_thread
    start_bot_thread()
    tz = get_timezone()
    hour, minute = get_report_hour_minute()
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        _send_daily_job,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_report",
    )
    logger.info("Scheduler started: daily report at %02d:%02d %s", hour, minute, tz)
    scheduler.start()
