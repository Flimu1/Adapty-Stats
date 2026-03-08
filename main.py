"""
Точка входа: загрузка конфига, планировщик APScheduler, опционально health check и test_send.
"""
import argparse
import logging
import os
import sys

from config import get_adapty_apps, get_telegram_chat_id, get_telegram_token

_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
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
    parser.add_argument(
        "--debug-adapty",
        action="store_true",
        help="Один запрос к Adapty (MRR для первого приложения), вывести сырой ответ и выйти",
    )
    parser.add_argument(
        "--debug-conversion",
        action="store_true",
        help="Запрос Conversion API (Install→Paid) для первого приложения, вывести сырой ответ",
    )
    args = parser.parse_args()

    if args.debug_conversion:
        from adapty_client import _debug_conversion_response
        _debug_conversion_response()
        return

    if args.debug_adapty:
        from adapty_client import _debug_adapty_response
        _debug_adapty_response()
        return

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
