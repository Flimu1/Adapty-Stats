"""
Клиент к Adapty Analytics Export API.
Собирает MRR и Installs по приложениям; параллельный сбор через concurrent.futures.
API: POST /api/v1/client-api/metrics/analytics/ (api-admin.adapty.io)
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Optional, Tuple, Union
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_analytics_path,
    get_adapty_conversion_path,
    get_adapty_timezone,
)

logger = logging.getLogger(__name__)


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


def _fetch_chart(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    chart_id: str,
    date_from: datetime,
    date_to: datetime,
) -> Union[float, int, None]:
    """
    Один запрос к Adapty за одну метрику (mrr или installs).
    Возвращает значение value из ответа или None при ошибке.
    Для периодов > 365 дней API требует period_unit=month (daily нельзя).
    """
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }
    days = (date_to - date_from).days
    period_unit = "month" if days > 365 else "day"
    body = {
        "chart_id": chart_id,
        "filters": {
            "date": [date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")],
        },
        "period_unit": period_unit,
        "format": "json",
    }
    try:
        session = _get_session()
        resp = session.post(url, json=body, headers=headers, timeout=30)
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
        return None
    except ValueError as e:
        logger.exception("Adapty API invalid JSON (chart_id=%s): %s", chart_id, e)
        return None

    # Парсим значение метрики. Реальный ответ Adapty:
    # - MRR: data.revenue.value (или legacy data.gross_revenue.value), не data.mrr!
    # - Installs: data.<ключ>.value (уточняется по ответу)
    # При длинном периоде API возвращает data.*.data = [ {date, value}, ... ] — берём последнюю точку (конец периода).
    data_obj = data.get("data") or {}
    if not isinstance(data_obj, dict):
        return None

    def _value_from_metric(metric: dict, as_float: bool) -> Union[float, int, None]:
        """Берёт value из metric.value или из последней точки metric.data (конец периода)."""
        val = metric.get("value")
        if val is not None:
            try:
                return float(val) if as_float else int(float(val))
            except (TypeError, ValueError):
                pass
        arr = metric.get("data")
        if isinstance(arr, list) and arr:
            # Для периода в несколько дней API возвращает массив по дням — нужна последняя точка
            last_point = arr[-1] if isinstance(arr[-1], dict) else None
            if last_point is not None:
                val = last_point.get("value")
                if val is not None:
                    try:
                        return float(val) if as_float else int(float(val))
                    except (TypeError, ValueError):
                        pass
        return None

    # Для MRR и ARR берём выручку как в дашборде (revenue / gross_revenue).
    # proceeds — это выручка после комиссий, она заметно ниже и не совпадает с карточкой MRR.
    if chart_id in ("mrr", "arr"):
        for key in ("revenue", "gross_revenue", "proceeds", "mrr", "arr"):
            metric = data_obj.get(key)
            if metric is not None and isinstance(metric, dict):
                val = _value_from_metric(metric, as_float=True)
                if val is not None:
                    return float(val)
        logger.warning(
            "Adapty API: метрика MRR/revenue не найдена, keys=%s", list(data_obj.keys())
        )
        return None

    elif chart_id == "revenue":
        for key in ("revenue", "gross_revenue", "proceeds"):
            metric = data_obj.get(key)
            if metric is not None and isinstance(metric, dict):
                val = _value_from_metric(metric, as_float=True)
                if val is not None:
                    return float(val)
        logger.warning(
            "Adapty API: метрика revenue не найдена, keys=%s", list(data_obj.keys())
        )
        return None

    # Installs: API возвращает data.common.value (не data.installs!)
    for key in ("common", chart_id, "installs", "new_installs"):
        metric = data_obj.get(key)
        if metric is not None and isinstance(metric, dict):
            val = _value_from_metric(metric, as_float=False)
            if val is not None:
                return int(val)

    logger.warning(
        "Adapty API: метрика не найдена для chart_id=%s, data keys=%s",
        chart_id,
        list(data_obj.keys()),
    )
    return None


def _fetch_conversion(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    date_from: datetime,
    date_to: datetime,
) -> Optional[float]:
    """
    Запрашивает когортную конверсию Install → Paid через Adapty Conversion API.
    Возвращает значение конверсии (процент 0–100 или доля 0–1) как float или None при ошибке.
    """
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }
    body = {
        "filters": {
            "date": [date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")],
        },
        "from_period": None,
        "to_period": 1,
        "period_unit": "month",
        "date_type": "profile_install_date",
        "format": "json",
    }
    try:
        session = _get_session()
        resp = session.post(url, json=body, headers=headers, timeout=30)
        logger.debug(
            "Adapty Conversion API response: status=%s body=%s",
            resp.status_code,
            resp.text[:500] if resp.text else "(empty)",
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty Conversion API request failed: %s", e)
        return None
    except ValueError as e:
        logger.exception("Adapty Conversion API invalid JSON: %s", e)
        return None

    # Извлекаем значение конверсии из data (процент или доля)
    # API может вернуть data как массив [{value: X}] или объект {value: X}; также value на корне
    data_obj = data.get("data")
    root_value = data.get("value")
    if root_value is not None and isinstance(root_value, (int, float)):
        try:
            return float(root_value)
        except (TypeError, ValueError):
            pass

    if data_obj is None:
        return None

    def _extract_float(obj: Any) -> Optional[float]:
        if obj is None:
            return None
        if isinstance(obj, (int, float)):
            try:
                return float(obj)
            except (TypeError, ValueError):
                return None
        if isinstance(obj, dict):
            for key in ("value", "conversion", "rate", "percentage", "conv"):
                val = obj.get(key)
                if val is not None and isinstance(val, (int, float)):
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
            # data может содержать массив по периодам — берём последнее/среднее
            arr = obj.get("data")
            if isinstance(arr, list) and arr:
                last = arr[-1] if isinstance(arr[-1], dict) else None
                if last:
                    return _extract_float(last.get("value") or last.get("y"))
        if isinstance(obj, list) and obj:
            return _extract_float(obj[-1])
        return None

    # data может быть массивом периодов [{value, ...}, ...]
    result = _extract_float(data_obj)
    if result is not None:
        # Если API вернул долю (0–1), приводим к проценту (0–100)
        if 0 <= result <= 1:
            result = result * 100
        return float(result)
    logger.warning(
        "Adapty Conversion API: значение конверсии не найдено, data keys=%s",
        list(data_obj.keys()) if isinstance(data_obj, dict) else type(data_obj),
    )
    return None


def _debug_conversion_response() -> None:
    """
    Запрос Conversion API (Install→Paid) для первого приложения.
    Выводит сырой ответ для сверки с дашбордом Adapty.
    Запуск: python main.py --debug-conversion
    """
    import json
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    path = get_adapty_conversion_path()
    tz_str = get_adapty_timezone()
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("Europe/Minsk")
    now_local = datetime.now(tz)
    target_date = now_local.date()
    start_of_month = target_date.replace(day=1)
    date_from = datetime(start_of_month.year, start_of_month.month, start_of_month.day)
    date_to = datetime(target_date.year, target_date.month, target_date.day)
    app = apps[0]
    print("=== Adapty Conversion API (Install→Paid) ===")
    print(f"App: {app.name}")
    print(f"Period: {date_from.date()} — {date_to.date()}")
    print()
    conv = _fetch_conversion(app.api_key, base_url, path, tz_str, date_from, date_to)
    print(f"Parsed conversion: {f'{conv:.2f}%' if conv is not None else 'N/A'}")
    print()
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {app.api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": tz_str,
    }
    body = {
        "filters": {"date": [date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d")]},
        "from_period": None,
        "to_period": 1,
        "period_unit": "month",
        "date_type": "profile_install_date",
        "format": "json",
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        print("Raw response status:", resp.status_code)
        print("Raw response body:")
        if resp.text:
            try:
                j = resp.json()
                print(json.dumps(j, indent=2, ensure_ascii=False))
            except Exception:
                print(resp.text[:2000])
        else:
            print("(empty)")
    except Exception as e:
        print("Request failed:", e)


def _debug_adapty_response() -> None:
    """
    Выполняет один запрос к Adapty (MRR для первого приложения) и выводит сырой ответ.
    Запуск: python main.py --debug-adapty (или LOG_LEVEL=DEBUG python main.py --test-send).
    Даты запроса — в timezone отчёта (по умолчанию Europe/Minsk, GMT+3).
    """
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    path = get_adapty_analytics_path()
    tz_str = get_adapty_timezone()
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("Europe/Minsk")
    app = apps[0]
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    to_today = datetime.now(tz)
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
        "Adapty-Tz": tz_str,
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
    conversion_path: Optional[str] = None,
) -> dict[str, Union[float, int, None]]:
    """
    Четыре запроса к Adapty (mrr + installs + revenue + arr) и конверсия Install→Paid.
    Возвращает dict с ключами mrr, installs, revenue, arr, install_to_paid_conv.
    Значения могут быть None при ошибке запроса.
    """
    mrr = _fetch_chart(api_key, base_url, path, timezone, "mrr", date_from, date_to)
    installs = _fetch_chart(
        api_key, base_url, path, timezone, "installs", date_from, date_to
    )
    revenue = _fetch_chart(
        api_key, base_url, path, timezone, "revenue", date_from, date_to
    )
    arr = _fetch_chart(api_key, base_url, path, timezone, "arr", date_from, date_to)
    install_to_paid_conv = None
    if conversion_path:
        install_to_paid_conv = _fetch_conversion(
            api_key, base_url, conversion_path, timezone, date_from, date_to
        )
    return {
        "mrr": mrr,
        "installs": installs,
        "revenue": revenue,
        "arr": arr,
        "install_to_paid_conv": install_to_paid_conv,
    }


def _fetch_revenue_metric_last_two_days(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    date_yesterday: datetime,
    date_today: datetime,
    chart_id: str = "mrr",
) -> Tuple[Union[float, None], Union[float, None]]:
    """
    Запрашивает метрику выручки (MRR или ARR) за (вчера, сегодня) в календарных днях (в timezone отчёта).
    Возвращает (yesterday, today) по последним двум точкам data[0].values.
    При ошибке возвращает (None, None).
    Так дельта совпадает с дашбордом Adapty (5 фев = 307.07, 6 фев = 348.2).
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
            "date": [date_yesterday.strftime("%Y-%m-%d"), date_today.strftime("%Y-%m-%d")],
        },
        "period_unit": "day",
        "format": "json",
    }
    try:
        session = _get_session()
        resp = session.post(url, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("%s two-day request failed: %s", chart_id, e)
        return None, None

    data_obj = data.get("data") or {}
    for key in ("revenue", "gross_revenue", "proceeds", "mrr", "arr"):
        metric = data_obj.get(key)
        if not metric or not isinstance(metric, dict):
            continue
        arr = metric.get("data")
        if not isinstance(arr, list) or not arr:
            continue
        first = arr[0]
        if not isinstance(first, dict):
            continue
        values = first.get("values")
        if not isinstance(values, list) or len(values) < 1:
            continue
        try:
            y_today = float(values[-1].get("y", 0))
            y_yesterday = float(values[-2].get("y", 0)) if len(values) >= 2 else 0.0
            return y_yesterday, y_today
        except (TypeError, ValueError):
            continue
    return None, None


def fetch_all_metrics(
    report_date: Union[date, datetime, None] = None,
) -> list[dict[str, Any]]:
    """
    Собирает метрики по всем приложениям параллельно.
    По умолчанию строит отчёт за текущий день (в timezone данных Adapty).
    - MRR и Installs: за текущий месяц до report_date включительно.
    - Дельта MRR: report_date-1 vs report_date (календарные дни в timezone отчёта).
    - Установки «за сутки»: installs за report_date.
    Возвращает: name, mrr_total, mrr_delta_24h, installs_total, installs_delta_24h.
    """
    apps = get_adapty_apps()
    base_url = get_adapty_base_url()
    path = get_adapty_analytics_path()
    conversion_path = get_adapty_conversion_path()
    tz_str = get_adapty_timezone()

    # Текущий месяц и «вчера/сегодня» в timezone отчёта (как в Adapty)
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    local_today = now_local.date()
    if report_date is None:
        target_date = local_today
    elif isinstance(report_date, datetime):
        target_date = report_date.date()
    else:
        target_date = report_date

    prev_date = target_date - timedelta(days=1)
    start_of_month = target_date.replace(day=1)

    date_start_month = datetime(start_of_month.year, start_of_month.month, start_of_month.day)
    date_target = datetime(target_date.year, target_date.month, target_date.day)
    date_prev = datetime(prev_date.year, prev_date.month, prev_date.day)

    results: list[dict[str, Any]] = []

    def job(app_index: int, app_key: str, app_name: str, is_visible: bool) -> dict[str, Any]:
        # Метрики за месяц (MRR на конец периода, installs — сумма за месяц)
        month_data = fetch_metrics_for_app(
            app_key,
            base_url,
            path,
            tz_str,
            date_start_month,
            date_target,
            conversion_path=conversion_path,
        )
        mrr_month = month_data.get("mrr")
        inst_month = month_data.get("installs")
        revenue_month = month_data.get("revenue")
        arr_total = month_data.get("arr")
        conv_rate = month_data.get("install_to_paid_conv")

        # Дельта MRR за сутки: предыдущий закрытый день vs report_date.
        mrr_yesterday, mrr_today = _fetch_revenue_metric_last_two_days(
            app_key, base_url, path, tz_str, date_prev, date_target, chart_id="mrr"
        )
        if mrr_today is not None and mrr_yesterday is not None:
            mrr_delta_24h = float(mrr_today) - float(mrr_yesterday)
        else:
            mrr_delta_24h = None

        # Дельта ARR за сутки
        arr_yesterday, arr_today = _fetch_revenue_metric_last_two_days(
            app_key, base_url, path, tz_str, date_prev, date_target, chart_id="arr"
        )
        if arr_today is not None and arr_yesterday is not None:
            arr_delta_24h = float(arr_today) - float(arr_yesterday)
        else:
            arr_delta_24h = None

        # Revenue за сутки (выручка за report_date)
        _, rev_today = _fetch_revenue_metric_last_two_days(
            app_key, base_url, path, tz_str, date_prev, date_target, chart_id="revenue"
        )
        revenue_per_day = float(rev_today) if rev_today is not None else None

        # Установки за report_date: один календарный день.
        inst_today = _fetch_chart(
            app_key, base_url, path, tz_str, "installs", date_target, date_target
        )
        inst_delta_24h = int(inst_today) if inst_today is not None else None

        return {
            "index": app_index,
            "name": app_name,
            "mrr_total": mrr_month,
            "mrr_delta_24h": mrr_delta_24h,
            "installs_total": inst_month,
            "installs_delta_24h": inst_delta_24h,
            "revenue_total": revenue_month,
            "revenue_per_day": revenue_per_day,
            "arr_total": arr_total,
            "arr_delta_24h": arr_delta_24h,
            "conv_rate": conv_rate,
            "is_visible": is_visible,
        }

    with ThreadPoolExecutor(max_workers=min(len(apps), 6)) as executor:
        futures = {
            executor.submit(job, i, app.api_key, app.name, app.is_visible): i
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
                        "mrr_total": None,
                        "mrr_delta_24h": None,
                        "installs_total": None,
                        "installs_delta_24h": None,
                        "revenue_total": None,
                        "revenue_per_day": None,
                        "arr_total": None,
                        "arr_delta_24h": None,
                        "conv_rate": None,
                        "is_visible": apps[idx].is_visible,
                    }
                )

    results.sort(key=lambda r: r["index"])
    return results
