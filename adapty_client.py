"""
Клиент к Adapty Analytics Export API.
Собирает MRR и Installs по приложениям; параллельный сбор через concurrent.futures.
API: POST /api/v1/client-api/metrics/analytics/ (api-admin.adapty.io)
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Union

import requests

from config import (
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_analytics_path,
    get_timezone,
)

logger = logging.getLogger(__name__)


def _fetch_chart(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    chart_id: str,
    date_from: datetime,
    date_to: datetime,
) -> Union[float, int]:
    """
    Один запрос к Adapty за одну метрику (mrr или installs).
    Возвращает значение value из ответа.
    """
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }
    body = {
        "chart_id": chart_id,
        "filters": {
            "date": [date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")],
        },
        "period_unit": "day",
        "format": "json",
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty API request failed (chart_id=%s): %s", chart_id, e)
        return 0.0 if chart_id == "mrr" else 0
    except ValueError as e:
        logger.exception("Adapty API invalid JSON (chart_id=%s): %s", chart_id, e)
        return 0.0 if chart_id == "mrr" else 0

    # Ответ: { "data": { "mrr": { "value": 123.45, ... }, ... } }
    # или { "data": { "installs": { "value": 100, ... }, ... } }
    data_obj = data.get("data") or {}
    metric = data_obj.get(chart_id)
    if metric is None:
        return 0.0 if chart_id == "mrr" else 0
    val = metric.get("value")
    if val is None:
        return 0.0 if chart_id == "mrr" else 0
    try:
        return float(val) if chart_id == "mrr" else int(val)
    except (TypeError, ValueError):
        return 0.0 if chart_id == "mrr" else 0


def fetch_metrics_for_app(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, Union[float, int]]:
    """
    Два запроса к Adapty (mrr + installs) за период [date_from, date_to].
    Возвращает dict с ключами mrr, installs.
    """
    mrr = _fetch_chart(api_key, base_url, path, timezone, "mrr", date_from, date_to)
    installs = _fetch_chart(
        api_key, base_url, path, timezone, "installs", date_from, date_to
    )
    return {"mrr": float(mrr), "installs": int(installs)}


def fetch_all_metrics() -> list[dict[str, Any]]:
    """
    Собирает метрики по всем приложениям параллельно.
    Для каждого приложения: MRR и Installs за последние 24ч и за предыдущие 24ч.
    Total = за последние 24ч, Delta = разница с предыдущими 24ч.
    Возвращает: name, mrr_total, mrr_delta_24h, installs_total, installs_delta_24h.
    """
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    path = get_adapty_analytics_path()
    tz = get_timezone()

    # Период "сегодня" — последние 24 часа
    to_today = datetime.utcnow()
    from_today = to_today - timedelta(hours=24)
    # Период "вчера" — предыдущие 24 часа (для дельты)
    to_yesterday = from_today
    from_yesterday = to_yesterday - timedelta(hours=24)

    results: list[dict[str, Any]] = []

    def job(app_index: int, app_key: str, app_name: str) -> dict[str, Any]:
        current = fetch_metrics_for_app(
            app_key, base_url, path, tz, from_today, to_today
        )
        previous = fetch_metrics_for_app(
            app_key, base_url, path, tz, from_yesterday, to_yesterday
        )
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
            executor.submit(job, i, app.api_key, app.name): i
            for i, app in enumerate(apps)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.exception("Failed to fetch app metrics: %s", e)
                idx = futures[future]
                results.append(
                    {
                        "index": idx,
                        "name": apps[idx].name,
                        "mrr_total": 0.0,
                        "mrr_delta_24h": 0.0,
                        "installs_total": 0,
                        "installs_delta_24h": 0,
                    }
                )

    results.sort(key=lambda r: r["index"])
    return results
