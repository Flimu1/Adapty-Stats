"""
Telegram-бот: приём команд и кнопка «Собрать данные» для принудительного сбора отчёта с Adapty.
Работает в фоне (long polling) вместе с планировщиком.
"""
import json
import logging
import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    get_report_time,
    get_telegram_admin_id,
    get_telegram_chat_id,
    get_telegram_token,
    set_report_time,
)

logger = logging.getLogger(__name__)

# Состояние ожидания ввода времени (chat_id -> "set_time")
_pending_state: dict[str, str] = {}

TELEGRAM_API = "https://api.telegram.org/bot"

from typing import Union, Optional

def _is_admin_only_mode() -> bool:
    """True, если управление только из лички (задан TELEGRAM_ADMIN_ID)."""
    return get_telegram_admin_id() is not None


# Триггеры для ручного сбора (команда или текст кнопки)
COLLECT_TRIGGERS = frozenset({
    "/collect", "/data", "/report",
    "collect data", "collect", "receipt data", "get data",
    "собрать данные", "собрать", "получить отчёт", "📊 collect data",
})


def _api(method: str, payload: dict) -> Optional[dict]:
    """POST к Telegram Bot API. Возвращает JSON или None при ошибке."""
    token = get_telegram_token()
    url = f"{TELEGRAM_API}{token}/{method}"
    try:
        session = _get_session()
        r = session.post(url, json=payload, timeout=25)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.warning("Telegram API %s failed: %s", method, e)
        return None


def _send(chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
    """Отправить сообщение в чат, опционально с клавиатурой."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    result = _api("sendMessage", payload)
    return result is not None and result.get("ok") is True


def _answer_callback(callback_query_id: str, text: Optional[str] = None) -> bool:
    """Ответ на нажатие inline-кнопки (убирает «часики» у пользователя)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    result = _api("answerCallbackQuery", payload)
    return result is not None and result.get("ok") is True


def _collect_and_send(chat_id: str, to_group: bool = False) -> tuple[bool, str]:
    """
    Собрать данные с Adapty и отправить отчёт (в группу через send_message).
    Возвращает (успех, сообщение для пользователя в текущий чат).
    to_group: если True, в ответе пользователю пишем «отправлен в группу».
    """
    try:
        from report_builder import build_report
        from telegram_sender import send_message
        from config import get_telegram_admin_id

        report = build_report()
        text = report.text
        if not text:
            text = "📊 Данные не получены. Проверьте логи и настройки Adapty."
        if send_message(text):
            has_anomalies = bool(report.anomalies)
            sent_to_admin = False
            if has_anomalies:
                admin_id = get_telegram_admin_id()
                if admin_id:
                    details = "\n".join(f"• {a}" for a in report.anomalies[:20])
                    alert = (
                        f"⚠️ Обнаружены аномалии в отчёте за {report.report_date.strftime('%d.%m.%Y')}\n\n"
                        f"{details}"
                    )
                    sent_to_admin = send_message(alert, chat_id=admin_id)
            if to_group:
                msg = "✅ Отчёт отправлен в группу."
            else:
                msg = "✅ Отчёт собран и отправлен."
            if has_anomalies:
                msg += " ⚠️ Есть аномалии в данных."
                if sent_to_admin:
                    msg += " Подробности отправлены администратору."
            return True, msg
        return False, "❌ Не удалось отправить отчёт."
    except Exception as e:
        logger.exception("Collect and send failed: %s", e)
        return False, f"❌ Ошибка: {e!s}"


def _inline_keyboard() -> dict:
    """Inline-клавиатура: «Собрать данные» и «Установить время сбора»."""
    return {
        "inline_keyboard": [
            [{"text": "📊 Собрать данные", "callback_data": "collect"}],
            [{"text": "⏰ Установить время сбора", "callback_data": "settime"}],
        ]
    }


def _handle_set_time_input(chat_id: str, text: str) -> bool:
    """Обработка ввода времени (формат ЧЧ:ММ). Возвращает True если обработано."""
    if _pending_state.pop(chat_id, None) != "set_time":
        return False
    ok, err = set_report_time(text)
    if not ok:
        _pending_state[chat_id] = "set_time"
        _send(chat_id, f"❌ {err}\n\nПопробуйте снова в формате ЧЧ:ММ (например, 09:00):")
        return True
    # Успешно сохранили — переназначаем задачу в планировщике
    m = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        from scheduler import reschedule_daily_report
        if reschedule_daily_report(hour, minute):
            _send(chat_id, f"✅ Время сбора установлено на <b>{text}</b>. Отчёт будет отправляться ежедневно в это время.", _inline_keyboard())
        else:
            _send(chat_id, f"✅ Время сохранено ({text}), но не удалось обновить планировщик. Перезапустите приложение.", _inline_keyboard())
    else:
        _send(chat_id, f"✅ Время сохранено: {text}", _inline_keyboard())
    return True


def _handle_message(chat_id: str, text: str) -> bool:
    """Обработка текстового сообщения. Возвращает True если обработано."""
    if not text:
        return False
    text_lower = text.strip().lower()
    # Отмена ожидания ввода времени
    if text_lower in ("/cancel", "отмена", "cancel"):
        if chat_id in _pending_state:
            _pending_state.pop(chat_id, None)
            _send(chat_id, "Отменено.", _inline_keyboard())
            return True
    # Ожидание ввода времени
    if _handle_set_time_input(chat_id, text):
        return True
    # Приветствие и подсказка
    if text_lower in ("/start", "/help"):
        current_time = get_report_time()
        if _is_admin_only_mode():
            welcome = (
                "👋 <b>Adapty Daily Report Bot</b> (управление из лички)\n\n"
                "• Ежедневный отчёт уходит в группу по расписанию (<b>{}</b>).\n"
                "• <b>Собрать данные</b> — отправить отчёт в группу сейчас.\n"
                "• <b>Установить время сбора</b> — изменить время."
            ).format(current_time)
        else:
            welcome = (
                "👋 <b>Adapty Daily Report Bot</b>\n\n"
                "• Ежедневный отчёт приходит по расписанию (<b>{}</b>).\n"
                "• Нажми <b>Собрать данные</b> — чтобы получить отчёт прямо сейчас.\n"
                "• Нажми <b>Установить время сбора</b> — чтобы изменить время."
            ).format(current_time)
        return _send(chat_id, welcome, _inline_keyboard())
    # Ручной сбор по команде или по тексту кнопки
    if text_lower in COLLECT_TRIGGERS or "collect" in text_lower and "data" in text_lower:
        _send(chat_id, "⏳ Собираю данные с Adapty…")
        ok, msg = _collect_and_send(chat_id, to_group=_is_admin_only_mode())
        _send(chat_id, msg)
        return True
    return False


def _handle_callback(chat_id: str, callback_query_id: str, data: str) -> bool:
    """Обработка нажатия inline-кнопки. Возвращает True если обработано."""
    if data == "collect":
        _answer_callback(callback_query_id, "Собираю данные…")
        ok, msg = _collect_and_send(chat_id, to_group=_is_admin_only_mode())
        _answer_callback(callback_query_id, "Готово!" if ok else None)
        _send(chat_id, msg)
        return True
    if data == "settime":
        _pending_state[chat_id] = "set_time"
        _answer_callback(callback_query_id, "Введите время…")
        current = get_report_time()
        _send(
            chat_id,
            f"⏰ Текущее время сбора: <b>{current}</b>\n\n"
            "Введите новое время в формате <b>ЧЧ:ММ</b> (например, 09:00 или 14:30).\n"
            "Для отмены отправьте /cancel.",
        )
        return True
    return False


def _accept_chat(chat_id: str, chat_type: str, group_chat_id: str, admin_id: Optional[str]) -> bool:
    """Решить, обрабатывать ли сообщение/колбек из этого чата."""
    if admin_id:
        # Режим «управление из лички»: принимаем только личку от админа
        return chat_type == "private" and chat_id == admin_id
    # Классический режим: только группа
    return chat_id == group_chat_id


def _send_admin_id_hint(chat_id: str, user_id: Union[int, str]) -> None:
    """Отправить в личку подсказку: ваш user ID и как добавить TELEGRAM_ADMIN_ID (Railway / .env)."""
    uid = str(user_id)
    hint = (
        "👤 <b>Ваш Telegram User ID:</b> <code>{uid}</code>\n\n"
        "Чтобы управлять ботом только из лички (отчёты по-прежнему в группу), добавьте переменную:\n\n"
        "• <b>Railway:</b> Variables → <code>TELEGRAM_ADMIN_ID</code> = <code>{uid}</code>\n"
        "• <b>Локально:</b> в <code>.env</code> строка <code>TELEGRAM_ADMIN_ID={uid}</code>\n\n"
        "После сохранения перезапустите приложение."
    ).format(uid=uid)
    _send(chat_id, hint)


def _process_update(group_chat_id: str, admin_id: Optional[str], update: dict) -> None:
    """Разобрать один update и вызвать нужный обработчик."""
    if "message" in update:
        msg = update["message"]
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = chat.get("type", "")
        # Если TELEGRAM_ADMIN_ID не задан и написали из лички — показываем user ID и подсказку для Railway/.env
        if not admin_id and chat_type == "private":
            user_id = msg.get("from", {}).get("id")
            if user_id is not None:
                _send_admin_id_hint(chat_id, user_id)
            return
        if not _accept_chat(chat_id, chat_type, group_chat_id, admin_id):
            return
        text = (msg.get("text") or "").strip()
        _handle_message(chat_id, text)
        return
    if "callback_query" in update:
        cq = update["callback_query"]
        chat = cq.get("message", {}).get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = chat.get("type", "")
        if not admin_id and chat_type == "private":
            user_id = cq.get("from", {}).get("id")
            if user_id is not None:
                _send_admin_id_hint(chat_id, user_id)
            _api("answerCallbackQuery", {"callback_query_id": cq["id"]})
            return
        if not _accept_chat(chat_id, chat_type, group_chat_id, admin_id):
            return
        _handle_callback(chat_id, cq["id"], (cq.get("data") or "").strip())
        return


def _get_session() -> requests.Session:
    """
    Возвращает requests.Session с настроенным HTTPAdapter и retry-логикой.
    Автоматически повторяет запросы при ошибках 500, 502, 503, 504 и проблемах с сетью.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def _poll_loop() -> None:
    """Бесконечный цикл long polling getUpdates. Устойчив к сетевым ошибкам."""
    token = get_telegram_token()
    group_chat_id = get_telegram_chat_id().strip()
    admin_id = get_telegram_admin_id()
    url = f"{TELEGRAM_API}{token}/getUpdates"
    offset = 0

    # Создаём сессию один раз для повторного использования
    session = _get_session()

    # Счётчик последовательных ошибок для экспоненциального backoff
    consecutive_errors = 0
    max_sleep = 60  # Максимальная пауза между попытками

    while True:
        try:
            r = session.get(
                url,
                params={"timeout": 50, "offset": offset},
                timeout=55,
            )
            r.raise_for_status()
            data = r.json()

            if not data.get("ok"):
                # API вернуло ошибку (например, неправильный токен)
                error_desc = data.get("description", "Unknown error")
                logger.warning("Telegram API returned error: %s", error_desc)
                time.sleep(5)
                continue

            # Успешный запрос — сбрасываем счётчик ошибок
            consecutive_errors = 0

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    _process_update(group_chat_id, admin_id, upd)
                except Exception as e:
                    # Ошибка обработки одного update не должна ломать весь цикл
                    logger.exception("Failed to process update %s: %s", upd.get("update_id"), e)

        except requests.exceptions.ReadTimeout as e:
            # Long polling timeout — это нормально, просто пробуем снова
            logger.debug("getUpdates read timeout (expected for long polling): %s", e)
            consecutive_errors = 0
            continue

        except requests.exceptions.ConnectionError as e:
            # Проблемы с соединением — ждём и пробуем снова
            consecutive_errors += 1
            sleep_time = min(5 * consecutive_errors, max_sleep)
            logger.warning(
                "getUpdates connection error (attempt %d): %s. Retrying in %ds...",
                consecutive_errors, e, sleep_time
            )
            time.sleep(sleep_time)

        except requests.RequestException as e:
            # Другие сетевые ошибки
            consecutive_errors += 1
            sleep_time = min(5 * consecutive_errors, max_sleep)
            logger.warning(
                "getUpdates request failed (attempt %d): %s. Retrying in %ds...",
                consecutive_errors, e, sleep_time
            )
            time.sleep(sleep_time)

        except Exception as e:
            # Любая другая непредвиденная ошибка — логируем и продолжаем
            consecutive_errors += 1
            sleep_time = min(10 * consecutive_errors, max_sleep)
            logger.exception(
                "Unexpected poll loop error (attempt %d): %s. Retrying in %ds...",
                consecutive_errors, e, sleep_time
            )
            time.sleep(sleep_time)


def start_bot_thread() -> threading.Thread:
    """Запустить бота в фоновом потоке (long polling). Возвращает поток."""
    thread = threading.Thread(target=_poll_loop, name="telegram-bot", daemon=True)
    thread.start()
    logger.info("Telegram bot thread started (Collect Data button)")
    return thread
