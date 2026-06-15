"""
Настройка APScheduler: ежедневная отправка отчёта в 09:00 Europe/Minsk.
"""
import datetime
import logging
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
    tz = ZoneInfo(tz_str)
    now_tz = datetime.datetime.now(tz)
    logger.info("=" * 50)
    logger.info("RUNNING SCHEDULED DAILY REPORT (triggered at %s %s)", now, tz_str)
    logger.info("Current time in timezone %s: %s", tz_str, now_tz)
    logger.info("=" * 50)
    
    from report_builder import build_report
    from telegram_sender import send_message
    from config import get_telegram_admin_id

    try:
        report = build_report()
        if send_message(report.text):
            logger.info("Daily report sent successfully")
            from report_delivery import send_followup_reports

            send_followup_reports(report.report_date)
            if report.anomalies:
                logger.warning(
                    "Anomalies detected for report date %s: %s",
                    report.report_date,
                    report.anomalies,
                )
                admin_id = get_telegram_admin_id()
                if admin_id:
                    details = "\n".join(f"• {a}" for a in report.anomalies[:20])
                    alert = (
                        f"⚠️ Обнаружены аномалии в отчёте за {report.report_date.strftime('%d.%m.%Y')}\n\n"
                        f"{details}"
                    )
                    send_message(alert, chat_id=admin_id)
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
    logger.info("reschedule_daily_report called: hour=%d, minute=%d, _scheduler=%s", hour, minute, _scheduler)
    if _scheduler is None:
        logger.error("Cannot reschedule: scheduler is None (not started yet)")
        return False
    try:
        tz_str = get_timezone()
        tz = ZoneInfo(tz_str)
        now_tz = datetime.datetime.now(tz)
        # Явно указываем day='*' для ежедневного выполнения
        trigger = CronTrigger(hour=hour, minute=minute, day='*', timezone=tz)
        logger.info("Rescheduling job with trigger: hour=%d, minute=%d, timezone=%s", hour, minute, tz_str)
        _scheduler.reschedule_job(
            "daily_report",
            trigger=trigger,
        )
        # Проверяем что следующий запуск вычислен
        job = _scheduler.get_job("daily_report")
        if job and hasattr(job, 'trigger'):
            next_run = job.trigger.get_next_fire_time(None, now_tz)
        else:
            next_run = None
        logger.info("Daily report rescheduled to %02d:%02d %s, next run: %s (current time: %s)", hour, minute, tz_str, next_run, now_tz)
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

    _scheduler = BlockingScheduler(timezone=tz)
    # Явно указываем day='*' для ежедневного выполнения
    trigger = CronTrigger(hour=hour, minute=minute, day='*', timezone=tz)
    _scheduler.add_job(
        _send_daily_job,
        trigger=trigger,
        id="daily_report",
    )
    
    logger.info(
        "Scheduler configured: daily report at %02d:%02d %s (trigger: %s)",
        hour, minute, tz_str, trigger,
    )
    
    _scheduler.start()
    
    # Логируем next_run_time после start(), когда планировщик вычислил его
    job = _scheduler.get_job("daily_report")
    now_tz = datetime.datetime.now(tz)
    if job:
        logger.info("Job details: id=%s, name=%s, trigger=%s", job.id, job.name, job.trigger)
        if hasattr(job, 'trigger'):
            next_run = job.trigger.get_next_fire_time(None, now_tz)
            logger.info(
                "Scheduler started: next run at %s (current time: %s)",
                next_run, now_tz
            )
        else:
            logger.warning("Job has no trigger attribute")
    else:
        logger.error("Job 'daily_report' not found after scheduler start!")
