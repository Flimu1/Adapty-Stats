"""
Настройка APScheduler: ежедневная отправка отчёта в 09:00 Europe/Minsk.
"""
import datetime
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_report_hour_minute, get_timezone

from typing import Optional

logger = logging.getLogger(__name__)

_scheduler: Optional[BlockingScheduler] = None


def _send_daily_job() -> None:
    """Job для планировщика: собрать отчёт и отправить в Telegram."""
    now = datetime.datetime.now()
    tz_str = get_timezone()
    logger.info("=" * 50)
    logger.info("RUNNING SCHEDULED DAILY REPORT (triggered at %s %s)", now, tz_str)
    logger.info("=" * 50)
    
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
        logger.error("Cannot reschedule: scheduler is None (not started yet)")
        return False
    try:
        tz_str = get_timezone()
        tz = ZoneInfo(tz_str)
        # start_date в прошлом для корректного планирования
        start_date = datetime.datetime.now(tz) - timedelta(days=1)
        trigger = CronTrigger(hour=hour, minute=minute, timezone=tz, start_date=start_date)
        _scheduler.reschedule_job(
            "daily_report",
            trigger=trigger,
        )
        # Проверяем что следующий запуск вычислен
        job = _scheduler.get_job("daily_report")
        if job and hasattr(job, 'trigger'):
            next_run = job.trigger.get_next_fire_time(None, datetime.datetime.now(tz))
        else:
            next_run = None
        logger.info("Daily report rescheduled to %02d:%02d %s, next run: %s", hour, minute, tz_str, next_run)
        return True
    except Exception as e:
        logger.exception("Failed to reschedule: %s", e)
        return False


def run_scheduler() -> None:
    """Запускает блокирующий планировщик с одной задачей в 09:00 по местному времени."""
    global _scheduler
    from telegram_bot import start_bot_thread
    start_bot_thread()
    tz_str = get_timezone()
    tz = ZoneInfo(tz_str)
    hour, minute = get_report_hour_minute()
    
    # start_date в прошлом, чтобы CronTrigger точно запланировал ближайший следующий запуск
    start_date = datetime.datetime.now(tz) - timedelta(days=1)
    
    _scheduler = BlockingScheduler(timezone=tz)
    trigger = CronTrigger(hour=hour, minute=minute, timezone=tz, start_date=start_date)
    _scheduler.add_job(
        _send_daily_job,
        trigger=trigger,
        id="daily_report",
    )
    
    logger.info(
        "Scheduler configured: daily report at %02d:%02d %s, start_date=%s",
        hour, minute, tz_str, start_date,
    )
    
    _scheduler.start()
    
    # Логируем next_run_time после start(), когда планировщик вычислил его
    job = _scheduler.get_job("daily_report")
    if job and hasattr(job, 'trigger'):
        next_run = job.trigger.get_next_fire_time(None, datetime.datetime.now(tz))
    else:
        next_run = None
    logger.info(
        "Scheduler started: next run at %s",
        next_run,
    )
