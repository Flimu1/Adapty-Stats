"""
Клиент к Adapty Analytics Export API.
Запросы MRR и Installs по приложениям; параллельный сбор через concurrent.futures.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import requests

from config import (
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_export_path,
    get_timezone,
)

logger = logging.getLogger(__name__)


def _parse_analytics_response(data: Any, period_hours: int) -> dict[str, float | int]:
    """
    Парсит ответ Adapty Export API в единый формат.
    Реальная структура ответа может отличаться — при необходимости адаптировать под свой API.
    Ожидаем поля: mrr (или revenue/mrr_total), installs (или new_users/installs_total).
    """
    out: dict[str, float | int] = {
        "mrr": 0.0,
        "installs": 0,
    }
    if not data:
        return out

    # Вариант: ответ — объект с полями верхнего уровня
    if isinstance(data, dict):
        # MRR: возможные имена полей в ответе API
        for key in ("mrr", "mrr_total", "revenue", "total_mrr"):
            if key in data and data[key] is not None:
                try:
                    out["mrr"] = float(data[key])
                except (TypeError, ValueError):
                    pass
                break
        # Installs
        for key in ("installs", "installs_total", "new_users", "total_installs", "users"):
            if key in data and data[key] is not None:
                try:
                    out["installs"] = int(data[key])
                except (TypeError, ValueError):
                    pass
                break
        # Вложенная структура data.data или data.analytics
        if out["mrr"] == 0 and out["installs"] == 0:
            for nested in ("data", "analytics", "metrics"):
                if nested in data and isinstance(data[nested], dict):
                    out = _parse_analytics_response(data[nested], period_hours)
                    break
                if nested in data and isinstance(data[nested], list) and data[nested]:
                    # Агрегируем по первой записи или сумме
                    first = data[nested][0]
                    if isinstance(first, dict):
                        out = _parse_analytics_response(first, period_hours)
                    break
    return out


def fetch_metrics_for_app(
    api_key: str,
    base_url: str,
    timezone: str,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, float | int]:
    """
    Один запрос к Adapty Export API за период [date_from, date_to].
    Возвращает dict с ключами mrr, installs.
    """
    path = get_adapty_export_path()
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }
    body = {
        "date_from": date_from.strftime("%Y-%m-%d"),
        "date_to": date_to.strftime("%Y-%m-%d"),
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty API request failed: %s", e)
        return {"mrr": 0.0, "installs": 0}
    except ValueError as e:
        logger.exception("Adapty API invalid JSON: %s", e)
        return {"mrr": 0.0, "installs": 0}

    period_hours = int((date_to - date_from).total_seconds() / 3600)
    return _parse_analytics_response(data, period_hours)


def fetch_all_metrics() -> list[dict[str, Any]]:
    """
    Собирает метрики по всем приложениям параллельно.
    Для каждого приложения: текущие MRR/Installs и значения за предыдущие 24ч для дельты.
    Возвращает список словарей: name, mrr_total, mrr_delta_24h, installs_total, installs_delta_24h.
    """
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    tz = get_timezone()
    now = datetime.utcnow()
    # Период "сейчас" — последние доступные данные (сегодня)
    to_today = now
    from_today = now - timedelta(days=1)
    # Период "24ч назад" — для расчёта дельты
    to_yesterday = now - timedelta(hours=24)
    from_yesterday = now - timedelta(hours=48)

    results: list[dict[str, Any]] = []

    def job(app_index: int, app_key: str, app_name: str) -> dict[str, Any]:
        current = fetch_metrics_for_app(app_key, base_url, tz, from_today, to_today)
        previous = fetch_metrics_for_app(app_key, base_url, tz, from_yesterday, to_yesterday)
        mrr_total = current.get("mrr") or 0
        mrr_prev = previous.get("mrr") or 0
        inst_total = current.get("installs") or 0
        inst_prev = previous.get("installs") or 0
        return {
            "index": app_index,
            "name": app_name,
            "mrr_total": float(mrr_total),
            "mrr_delta_24h": float(mrr_total) - float(mrr_prev),
            "installs_total": int(inst_total),
            "installs_delta_24h": int(inst_total) - int(inst_prev),
        }

    with ThreadPoolExecutor(max_workers=min(len(apps), 6)) as executor:
        futures = {
            executor.submit(
                job,
                i,
                app.api_key,
                app.name,
            ): i
            for i, app in enumerate(apps)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.exception("Failed to fetch app metrics: %s", e)
                idx = futures[future]
                results.append({
                    "index": idx,
                    "name": apps[idx].name,
                    "mrr_total": 0.0,
                    "mrr_delta_24h": 0.0,
                    "installs_total": 0,
                    "installs_delta_24h": 0,
                })

    results.sort(key=lambda r: r["index"])
    return results
