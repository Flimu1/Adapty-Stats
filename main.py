"""
Точка входа: загрузка конфига, планировщик APScheduler, опционально health check и test_send.
"""
import argparse
import logging
import sys

from config import get_adapty_apps, get_telegram_chat_id, get_telegram_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Adapty Daily Report Bot")
    parser.add_argument(
        "--test-send",
        action="store_true",
        help="Собрать отчёт по Adapty и один раз отправить в Telegram, затем выйти",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Проверить конфиг и вывести OK (для health check endpoint)",
    )
    args = parser.parse_args()

    if args.health:
        try:
            get_telegram_token()
            get_telegram_chat_id()
            get_adapty_apps()
            print("OK")
        except Exception as e:
            logger.error("Health check failed: %s", e)
            sys.exit(1)
        return

    if args.test_send:
        from telegram_sender import test_send
        if test_send():
            logger.info("Test report sent")
        else:
            logger.error("Test send failed")
            sys.exit(1)
        return

    # Обычный режим: запуск планировщика
    from scheduler import run_scheduler
    run_scheduler()


if __name__ == "__main__":
    main()
