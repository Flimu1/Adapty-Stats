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

from config import get_report_time, get_telegram_chat_id, get_telegram_token, set_report_time

logger = logging.getLogger(__name__)

# Состояние ожидания ввода времени (chat_id -> "set_time")
_pending_state: dict[str, str] = {}

TELEGRAM_API = "https://api.telegram.org/bot"

# Триггеры для ручного сбора (команда или текст кнопки)
COLLECT_TRIGGERS = frozenset({
    "/collect", "/data", "/report",
    "collect data", "collect", "receipt data", "get data",
    "собрать данные", "собрать", "получить отчёт", "📊 collect data",
})


def _api(method: str, payload: dict) -> dict | None:
    """POST к Telegram Bot API. Возвращает JSON или None при ошибке."""
    token = get_telegram_token()
    url = f"{TELEGRAM_API}{token}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=25)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.warning("Telegram API %s failed: %s", method, e)
        return None


def _send(chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
    """Отправить сообщение в чат, опционально с клавиатурой."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    result = _api("sendMessage", payload)
    return result is not None and result.get("ok") is True


def _answer_callback(callback_query_id: str, text: str | None = None) -> bool:
    """Ответ на нажатие inline-кнопки (убирает «часики» у пользователя)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    result = _api("answerCallbackQuery", payload)
    return result is not None and result.get("ok") is True


def _collect_and_send(chat_id: str) -> tuple[bool, str]:
    """
    Собрать актуальные данные с Adapty и отправить отчёт в чат.
    Возвращает (успех, сообщение для пользователя).
    """
    try:
        from report_builder import build_report_text
        from telegram_sender import send_message
        text = build_report_text()
        if not text:
            text = "📊 Данные не получены. Проверьте логи и настройки Adapty."
        if send_message(text):
            return True, "✅ Отчёт собран и отправлен."
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
            _send(chat_id, f"✅ Время сбора установлено на *{text}*. Отчёт будет отправляться ежедневно в это время.", _inline_keyboard())
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
        welcome = (
            "👋 *Adapty Daily Report Bot*\n\n"
            "• Ежедневный отчёт приходит по расписанию (*{}*).\n"
            "• Нажми *Собрать данные* — чтобы получить отчёт прямо сейчас.\n"
            "• Нажми *Установить время сбора* — чтобы изменить время."
        ).format(current_time)
        return _send(chat_id, welcome, _inline_keyboard())
    # Ручной сбор по команде или по тексту кнопки
    if text_lower in COLLECT_TRIGGERS or "collect" in text_lower and "data" in text_lower:
        _send(chat_id, "⏳ Собираю данные с Adapty…")
        ok, msg = _collect_and_send(chat_id)
        _send(chat_id, msg)
        return True
    return False


def _handle_callback(chat_id: str, callback_query_id: str, data: str) -> bool:
    """Обработка нажатия inline-кнопки. Возвращает True если обработано."""
    if data == "collect":
        _answer_callback(callback_query_id, "Собираю данные…")
        ok, msg = _collect_and_send(chat_id)
        _answer_callback(callback_query_id, "Готово!" if ok else None)
        _send(chat_id, msg)
        return True
    if data == "settime":
        _pending_state[chat_id] = "set_time"
        _answer_callback(callback_query_id, "Введите время…")
        current = get_report_time()
        _send(
            chat_id,
            f"⏰ Текущее время сбора: *{current}*\n\n"
            "Введите новое время в формате *ЧЧ:ММ* (например, 09:00 или 14:30).\n"
            "Для отмены отправьте /cancel.",
        )
        return True
    return False


def _process_update(allowed_chat_id: str, update: dict) -> None:
    """Разобрать один update и вызвать нужный обработчик."""
    if "message" in update:
        msg = update["message"]
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != allowed_chat_id:
            return
        text = (msg.get("text") or "").strip()
        _handle_message(chat_id, text)
        return
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        if chat_id != allowed_chat_id:
            return
        _handle_callback(chat_id, cq["id"], (cq.get("data") or "").strip())
        return


def _poll_loop() -> None:
    """Бесконечный цикл long polling getUpdates."""
    token = get_telegram_token()
    allowed_chat_id = get_telegram_chat_id().strip()
    url = f"{TELEGRAM_API}{token}/getUpdates"
    offset = 0
    while True:
        try:
            r = requests.get(
                url,
                params={"timeout": 50, "offset": offset},
                timeout=55,
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                time.sleep(2)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                _process_update(allowed_chat_id, upd)
        except requests.RequestException as e:
            logger.warning("getUpdates failed: %s", e)
            time.sleep(5)
        except Exception as e:
            logger.exception("Poll loop error: %s", e)
            time.sleep(10)


def start_bot_thread() -> threading.Thread:
    """Запустить бота в фоновом потоке (long polling). Возвращает поток."""
    thread = threading.Thread(target=_poll_loop, name="telegram-bot", daemon=True)
    thread.start()
    logger.info("Telegram bot thread started (Collect Data button)")
    return thread
