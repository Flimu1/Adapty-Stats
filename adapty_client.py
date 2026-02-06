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
        logger.debug(
            "Adapty API response: status=%s chart_id=%s body=%s",
            resp.status_code,
            chart_id,
            resp.text[:500] if resp.text else "(empty)",
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty API request failed (chart_id=%s): %s", chart_id, e)
        return 0.0 if chart_id == "mrr" else 0
    except ValueError as e:
        logger.exception("Adapty API invalid JSON (chart_id=%s): %s", chart_id, e)
        return 0.0 if chart_id == "mrr" else 0

    # Парсим значение метрики. Реальный ответ Adapty:
    # - MRR: data.gross_revenue.value или data.proceeds.value (не data.mrr!)
    # - Installs: data.<ключ>.value (уточняется по ответу)
    # Также возможны: data[chart_id].value, data[chart_id].data[0].value, rows/series.
    data_obj = data.get("data") or {}
    if not isinstance(data_obj, dict):
        return 0.0 if chart_id == "mrr" else 0

    # Для MRR API возвращает gross_revenue и proceeds — берём gross_revenue (валовая выручка)
    if chart_id == "mrr":
        for key in ("gross_revenue", "proceeds", "mrr"):
            metric = data_obj.get(key)
            if metric is not None and isinstance(metric, dict):
                val = metric.get("value")
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
                # вложенный data[0].value
                arr = metric.get("data")
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    val = arr[0].get("value")
                    if val is not None:
                        try:
                            return float(val)
                        except (TypeError, ValueError):
                            pass
        logger.warning("Adapty API: MRR не найден в ответе, keys=%s", list(data_obj.keys()))
        return 0.0

    # Installs: API возвращает data.common.value (не data.installs!)
    for key in ("common", chart_id, "installs", "new_installs"):
        metric = data_obj.get(key)
        if metric is not None and isinstance(metric, dict):
            val = metric.get("value")
            if val is not None:
                try:
                    return int(float(val))
                except (TypeError, ValueError):
                    pass
            arr = metric.get("data")
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                val = arr[0].get("value")
                if val is not None:
                    try:
                        return int(float(val))
                    except (TypeError, ValueError):
                        pass

    logger.warning(
        "Adapty API: метрика не найдена для chart_id=%s, data keys=%s",
        chart_id,
        list(data_obj.keys()),
    )
    return 0


def _debug_adapty_response() -> None:
    """
    Выполняет один запрос к Adapty (MRR для первого приложения) и выводит сырой ответ.
    Запуск: python main.py --debug-adapty (или LOG_LEVEL=DEBUG python main.py --test-send).
    """
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    path = get_adapty_analytics_path()
    tz = get_timezone()
    app = apps[0]
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    to_today = datetime.utcnow()
    from_today = to_today - timedelta(hours=24)
    body = {
        "chart_id": "mrr",
        "filters": {
            "date": [from_today.strftime("%Y-%m-%d"), to_today.strftime("%Y-%m-%d")],
        },
        "period_unit": "day",
        "format": "json",
    }
    headers = {
        "Authorization": f"Api-Key {app.api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": tz,
    }
    for chart_id in ("mrr", "installs"):
        body_chart = {**body, "chart_id": chart_id}
        print(f"=== Adapty debug: chart_id={chart_id} ===")
        print("URL:", url)
        print("Body:", body_chart)
        try:
            resp = requests.post(url, json=body_chart, headers=headers, timeout=30)
            print("Status:", resp.status_code)
            # Показываем только ключи верхнего уровня и data.*
            if resp.ok and resp.text:
                try:
                    j = resp.json()
                    d = j.get("data") or {}
                    keys = list(d.keys()) if isinstance(d, dict) else []
                    print("data keys:", keys)
                    for k in keys[:3]:  # первые 3 ключа и их value
                        v = d.get(k)
                        if isinstance(v, dict):
                            print(f"  {k}.value =", v.get("value"))
                        else:
                            print(f"  {k} =", type(v).__name__)
                    if len(resp.text) < 1500:
                        print("Response:", resp.text[:1500])
                    else:
                        print("Response (first 800 chars):", resp.text[:800], "...")
                except Exception:
                    print("Response (raw):", resp.text[:1500])
            else:
                print("Response:", resp.text[:500] if resp.text else "(empty)")
        except Exception as e:
            print("Request failed:", e)
        print()


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
