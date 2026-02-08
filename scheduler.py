"""
Настройка APScheduler: ежедневная отправка отчёта в 09:00 Europe/Minsk.
"""
import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_report_hour_minute, get_timezone

from typing import Optional

logger = logging.getLogger(__name__)

_scheduler: Optional[BlockingScheduler] = None


def _send_daily_job() -> None:
    """Job для планировщика: собрать отчёт и отправить в Telegram."""
    logger.info("Running scheduled daily report (triggered at %s)", datetime.datetime.now())
    from report_builder import build_report_text
    from telegram_sender import send_message
    from config import get_telegram_admin_id

    try:
        text = build_report_text()
        if send_message(text):
            logger.info("Daily report sent successfully")
        else:
            logger.error("Failed to send daily report")
    except Exception as e:
        logger.exception("Daily report job failed: %s", e)
        # Отправляем аварийное уведомление администратору
        admin_id = get_telegram_admin_id()
        if admin_id:
            error_message = f"🚨 Ошибка при отправке ежедневного отчета: {e}"
            try:
                send_message(error_message, chat_id=admin_id)
            except Exception as send_err:
                logger.exception("Failed to send error notification to admin: %s", send_err)


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
    job = _scheduler.get_job("daily_report")
    # APScheduler 4.x: у Job нет атрибута next_run_time (есть в 3.x)
    next_run = getattr(job, "next_run_time", None) if job else None
    logger.info(
        "Scheduler started: daily report at %02d:%02d %s, next run: %s",
        hour, minute, tz, next_run,
    )
    _scheduler.start()
