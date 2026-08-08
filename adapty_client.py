"""
Клиент к Adapty Analytics Export API.
Собирает MRR и Installs по приложениям; параллельный сбор через concurrent.futures.
API: POST /api/v1/client-api/metrics/analytics/ (api-admin.adapty.io)
"""
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence, Union
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
from daily_metric_integrity import REPORT_VALUE_FIELDS, validate_app_metrics
from daily_report_contract import (
    DailyAppSlot,
    DailyMetricsSnapshot,
    IntegrityIssue,
    MetricProvenance,
    load_daily_portfolio,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChartMetric:
    """Summary and daily series returned by one Adapty analytics chart."""

    value: float
    daily_values: tuple[float, ...]
    daily_dates: tuple[str, ...]


@dataclass(frozen=True)
class ConversionMetric:
    """Install-to-paid percentage together with its reconciliation counts."""

    value: float
    value_from: int
    value_to: int


def _metric_key(chart_id: str) -> str:
    """Map a Dashboard-compatible chart to its gross Export API series."""
    if chart_id in {"mrr", "arr", "revenue"}:
        return "revenue"
    if chart_id == "installs":
        return "common"
    raise ValueError(f"Unsupported Adapty chart: {chart_id}")


def _parse_finite_number(value: Any) -> Optional[float]:
    """Accept real finite numbers but reject booleans and numeric garbage."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_count(value: Any) -> Optional[int]:
    """Parse a non-negative mathematical integer without truncation."""
    number = _parse_finite_number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _parse_point_date(value: Any) -> Optional[str]:
    """Normalize Adapty date or timestamp labels to an ISO calendar date."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _parse_chart_metric(
    payload: dict[str, Any], chart_id: str
) -> Optional[ChartMetric]:
    """Parse the summary and daily points without falling back to net proceeds."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    metric = data.get(_metric_key(chart_id))
    if not isinstance(metric, dict):
        return None
    if "value" not in metric:
        return None
    if chart_id == "installs":
        count_value = _parse_count(metric["value"])
        if count_value is None:
            return None
        value = float(count_value)
    else:
        parsed_value = _parse_finite_number(metric["value"])
        if parsed_value is None or (chart_id != "revenue" and parsed_value < 0):
            return None
        value = parsed_value

    daily_values: list[float] = []
    daily_dates: list[str] = []
    series = metric.get("data")
    if not isinstance(series, list) or len(series) != 1:
        return None
    first_series = series[0]
    if not isinstance(first_series, dict):
        return None
    values = first_series.get("values")
    if not isinstance(values, list) or not values:
        return None
    for point in values:
        if not isinstance(point, dict):
            return None
        point_date = _parse_point_date(point.get("x"))
        if point_date is None:
            return None
        if chart_id == "installs":
            point_count = _parse_count(point.get("y"))
            if point_count is None:
                return None
            point_value = float(point_count)
        else:
            parsed_point = _parse_finite_number(point.get("y"))
            if parsed_point is None or (chart_id != "revenue" and parsed_point < 0):
                return None
            point_value = parsed_point
        daily_dates.append(point_date)
        daily_values.append(point_value)
    return ChartMetric(
        value=value,
        daily_values=tuple(daily_values),
        daily_dates=tuple(daily_dates),
    )


def _parse_conversion_metric(payload: dict[str, Any]) -> Optional[ConversionMetric]:
    """Parse Adapty's percentage and the raw counts used to calculate it."""
    if payload.get("metric_name") != "install_paid":
        return None
    value = _parse_finite_number(payload.get("value"))
    value_from = _parse_count(payload.get("value_from"))
    value_to = _parse_count(payload.get("value_to"))
    if value is None or value_from is None or value_to is None:
        return None
    if not 0 <= value <= 100 or value_to > value_from:
        return None
    return ConversionMetric(value=value, value_from=value_from, value_to=value_to)


def _get_session() -> requests.Session:
    """
    Возвращает requests.Session с настроенным HTTPAdapter и retry-логикой.
    Повторяет rate-limit/server ошибки и учитывает Retry-After.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        respect_retry_after_header=True,
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
    *,
    session: Optional[requests.Session] = None,
) -> Optional[ChartMetric]:
    """
    Один запрос к Adapty за одну метрику.
    Возвращает summary и дневной ряд или None при ошибке.
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
        request_session = session or _get_session()
        resp = request_session.post(url, json=body, headers=headers, timeout=30)
        logger.debug(
            "Adapty API response: status=%s chart_id=%s date_from=%s date_to=%s period_unit=%s",
            resp.status_code,
            chart_id,
            body["filters"]["date"][0],
            body["filters"]["date"][1],
            period_unit,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty API request failed (chart_id=%s): %s", chart_id, e)
        return None
    except ValueError as e:
        logger.exception("Adapty API invalid JSON (chart_id=%s): %s", chart_id, e)
        return None

    metric = _parse_chart_metric(data, chart_id)
    if metric is None:
        data_obj = data.get("data")
        logger.warning(
            "Adapty API: gross metric not found for chart_id=%s, data keys=%s",
            chart_id,
            list(data_obj.keys()) if isinstance(data_obj, dict) else [],
        )
    return metric


def _fetch_conversion(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    date_from: datetime,
    date_to: datetime,
    *,
    session: Optional[requests.Session] = None,
) -> Optional[ConversionMetric]:
    """
    Запрашивает когортную конверсию Install → Paid через Adapty Conversion API.
    Возвращает процент и raw counts либо None при ошибке.
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
        request_session = session or _get_session()
        resp = request_session.post(url, json=body, headers=headers, timeout=30)
        logger.debug(
            "Adapty Conversion API response: status=%s date_from=%s date_to=%s metric=install_paid",
            resp.status_code,
            body["filters"]["date"][0],
            body["filters"]["date"][1],
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.exception("Adapty Conversion API request failed: %s", e)
        return None
    except ValueError as e:
        logger.exception("Adapty Conversion API invalid JSON: %s", e)
        return None

    metric = _parse_conversion_metric(data)
    if metric is None:
        logger.warning("Adapty Conversion API: incomplete install_paid response")
    return metric


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
    print(
        "Parsed conversion: "
        f"{f'{conv.value:.2f}% ({conv.value_to}/{conv.value_from})' if conv is not None else 'N/A'}"
    )
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


def _pace_request(previous_started_at: Optional[float]) -> float:
    """Keep sequential request starts at or below Adapty's two-per-second limit."""
    started_at = time.monotonic()
    if previous_started_at is not None:
        wait_seconds = 0.5 - (started_at - previous_started_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
            started_at = time.monotonic()
    return started_at


def _last_value(
    metric: Optional[ChartMetric], expected_date: datetime
) -> Optional[float]:
    """Return the final daily point only when it belongs to the report date."""
    expected = expected_date.strftime("%Y-%m-%d")
    if (
        metric is None
        or not metric.daily_values
        or not metric.daily_dates
        or metric.daily_dates[-1] != expected
    ):
        return None
    return metric.daily_values[-1]


def _last_delta(
    metric: Optional[ChartMetric], previous_date: datetime, report_date: datetime
) -> Optional[float]:
    """Return a delta only for the two exact requested calendar dates."""
    expected_dates = (
        previous_date.strftime("%Y-%m-%d"),
        report_date.strftime("%Y-%m-%d"),
    )
    if (
        metric is None
        or len(metric.daily_values) < 2
        or len(metric.daily_dates) < 2
        or metric.daily_dates[-2:] != expected_dates
    ):
        return None
    return metric.daily_values[-1] - metric.daily_values[-2]


def _fetch_app_snapshot(
    *,
    app_index: int,
    app_key: str,
    app_name: str,
    is_visible: bool,
    base_url: str,
    analytics_path: str,
    conversion_path: str,
    timezone: str,
    month_start: datetime,
    previous_date: datetime,
    report_date: datetime,
) -> dict[str, Any]:
    """Collect one internally consistent five-response application snapshot."""
    session = _get_session()
    request_started_at = _pace_request(None)
    mrr = _fetch_chart(
        app_key,
        base_url,
        analytics_path,
        timezone,
        "mrr",
        previous_date,
        report_date,
        session=session,
    )
    request_started_at = _pace_request(request_started_at)
    arr = _fetch_chart(
        app_key,
        base_url,
        analytics_path,
        timezone,
        "arr",
        previous_date,
        report_date,
        session=session,
    )
    request_started_at = _pace_request(request_started_at)
    revenue = _fetch_chart(
        app_key,
        base_url,
        analytics_path,
        timezone,
        "revenue",
        month_start,
        report_date,
        session=session,
    )
    request_started_at = _pace_request(request_started_at)
    installs = _fetch_chart(
        app_key,
        base_url,
        analytics_path,
        timezone,
        "installs",
        month_start,
        report_date,
        session=session,
    )
    _pace_request(request_started_at)
    conversion = _fetch_conversion(
        app_key,
        base_url,
        conversion_path,
        timezone,
        month_start,
        report_date,
        session=session,
    )

    installs_total = int(installs.value) if installs is not None else None
    installs_today = _last_value(installs, report_date)
    return {
        "index": app_index,
        "name": app_name,
        "mrr_total": _last_value(mrr, report_date),
        "mrr_delta_24h": _last_delta(mrr, previous_date, report_date),
        "installs_total": installs_total,
        "installs_delta_24h": (
            int(installs_today) if installs_today is not None else None
        ),
        "revenue_total": revenue.value if revenue is not None else None,
        "revenue_per_day": _last_value(revenue, report_date),
        "arr_total": _last_value(arr, report_date),
        "arr_delta_24h": _last_delta(arr, previous_date, report_date),
        "conv_rate": conversion.value if conversion is not None else None,
        "conv_from": conversion.value_from if conversion is not None else None,
        "conv_to": conversion.value_to if conversion is not None else None,
        "is_visible": is_visible,
    }


def _missing_app_row(
    slot: DailyAppSlot,
    issues: Sequence[IntegrityIssue],
) -> dict[str, Any]:
    relevant_issues = tuple(
        issue
        for issue in issues
        if issue.app_name == slot.name
    )
    return {
        "index": slot.index,
        "name": slot.name,
        **{field: None for field in REPORT_VALUE_FIELDS},
        "issues": relevant_issues,
        "is_visible": True,
    }


def _metric_provenance(
    month_start: datetime,
    previous_date: datetime,
    report_date: datetime,
) -> dict[str, MetricProvenance]:
    expected = report_date.date().isoformat()
    previous = previous_date.date().isoformat()
    month = month_start.date().isoformat()

    def analytics(
        metric_id: str,
        series_key: str,
        date_from: str,
    ) -> MetricProvenance:
        return MetricProvenance(
            endpoint_class="analytics",
            metric_id=metric_id,
            series_key=series_key,
            date_from=date_from,
            date_to=expected,
            expected_date=expected,
        )

    mrr = analytics("mrr", "data.revenue", previous)
    arr = analytics("arr", "data.revenue", previous)
    revenue = analytics("revenue", "data.revenue", month)
    installs = analytics("installs", "data.common", month)
    conversion = MetricProvenance(
        endpoint_class="conversion",
        metric_id="install_paid",
        series_key="value/value_from/value_to",
        date_from=month,
        date_to=expected,
        expected_date=expected,
    )
    return {
        "mrr_total": mrr,
        "mrr_delta_24h": mrr,
        "arr_total": arr,
        "arr_delta_24h": arr,
        "revenue_total": revenue,
        "revenue_per_day": revenue,
        "installs_total": installs,
        "installs_delta_24h": installs,
        "conv_rate": conversion,
        "conv_from": conversion,
        "conv_to": conversion,
    }


def fetch_daily_snapshot(
    report_date: Union[date, datetime, None] = None,
) -> DailyMetricsSnapshot:
    """
    Собирает метрики только по трём каноническим приложениям параллельно.
    По умолчанию строит отчёт за текущий день (в timezone данных Adapty).
    - MRR и ARR: текущая точка и дельта из одного двухдневного ряда.
    - Revenue и Installs: MTD summary и последний дневной point одного ответа.
    - Conversion: процент и raw counts одного MTD ответа.
    Возвращает типизированный снимок вместе с проблемами конфигурации.
    """
    portfolio = load_daily_portfolio()
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

    results: list[dict[str, Any]] = [
        validate_app_metrics(_missing_app_row(slot, portfolio.issues))
        for slot in portfolio.slots
        if slot.api_key is None
    ]

    def job(
        app_index: int, app_key: str, app_name: str, is_visible: bool
    ) -> dict[str, Any]:
        return _fetch_app_snapshot(
            app_index=app_index,
            app_key=app_key,
            app_name=app_name,
            is_visible=is_visible,
            base_url=base_url,
            analytics_path=path,
            conversion_path=conversion_path,
            timezone=tz_str,
            month_start=date_start_month,
            previous_date=date_prev,
            report_date=date_target,
        )

    fetchable_slots = [slot for slot in portfolio.slots if slot.api_key is not None]
    if fetchable_slots:
        with ThreadPoolExecutor(max_workers=min(len(fetchable_slots), 6)) as executor:
            futures = {
                executor.submit(
                    job,
                    slot.index,
                    slot.api_key,
                    slot.name,
                    True,
                ): slot
                for slot in fetchable_slots
            }
            for future in as_completed(futures):
                slot = futures[future]
                try:
                    row = future.result()
                except Exception as error:
                    logger.exception("Failed to fetch app metrics: %s", error)
                    fetch_issue = IntegrityIssue(
                        code="fetch.failed",
                        message=f"{slot.name}: metric collection failed",
                        app_name=slot.name,
                    )
                    row = _missing_app_row(slot, (fetch_issue,))
                results.append(validate_app_metrics(row))

    results.sort(key=lambda r: r["index"])
    provenance = _metric_provenance(date_start_month, date_prev, date_target)
    for row in results:
        row["provenance"] = provenance
    return DailyMetricsSnapshot(
        rows=tuple(results),
        portfolio_issues=portfolio.issues,
    )


def fetch_all_metrics(
    report_date: Union[date, datetime, None] = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for callers that still consume a row list."""
    return list(fetch_daily_snapshot(report_date).rows)
