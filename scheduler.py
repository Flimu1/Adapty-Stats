"""
Настройка APScheduler: ежедневная отправка отчёта в 09:00 Europe/Minsk.
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_report_hour_minute, get_timezone

logger = logging.getLogger(__name__)

_scheduler: BlockingScheduler | None = None


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


def reschedule_daily_report(hour: int, minute: int) -> bool:
    """
    Переназначает время ежедневного отчёта. Вызывается из бота.
    Возвращает True при успехе.
    """
    global _scheduler
    if _scheduler is None:
        return False
    try:
        tz = get_timezone()
        _scheduler.reschedule_job(
            "daily_report",
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        )
        logger.info("Daily report rescheduled to %02d:%02d", hour, minute)
        return True
    except Exception as e:
        logger.exception("Failed to reschedule: %s", e)
        return False


def run_scheduler() -> None:
    """Запускает блокирующий планировщик с одной задачей в 09:00 по местному времени."""
    global _scheduler
    from telegram_bot import start_bot_thread
    start_bot_thread()
    tz = get_timezone()
    hour, minute = get_report_hour_minute()
    _scheduler = BlockingScheduler(timezone=tz)
    _scheduler.add_job(
        _send_daily_job,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_report",
    )
    logger.info("Scheduler started: daily report at %02d:%02d %s", hour, minute, tz)
    _scheduler.start()
