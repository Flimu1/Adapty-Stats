"""
Сбор и форматирование Telegram overview для одного A/B-теста Adapty.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Union

import requests

from config import (
    get_ab_test_app_index,
    get_ab_test_name,
    get_ab_test_start_date,
    get_ab_test_variant_value,
    get_adapty_analytics_path,
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_cohort_path,
    get_adapty_funnel_path,
    get_adapty_timezone,
    is_ab_test_report_enabled,
)

logger = logging.getLogger(__name__)


@dataclass
class AbTestVariantConfig:
    label: str
    paywall_id: str
    paywall_name: str


@dataclass
class AbTestConfig:
    enabled: bool
    app_index: int
    app_name: str
    test_name: str
    start_date: date
    variant_a: AbTestVariantConfig
    variant_b: AbTestVariantConfig


@dataclass
class AbTestVariantMetrics:
    label: str
    paywall_name: str
    revenue: Optional[float]
    paywall_views: Optional[int]
    purchases: Optional[int]
    arpas: Optional[float] = None

    @property
    def conversion_rate(self) -> Optional[float]:
        if self.paywall_views is None or self.purchases is None or self.paywall_views <= 0:
            return None
        return (float(self.purchases) / float(self.paywall_views)) * 100.0


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_num(n: Union[float, int, None]) -> str:
    if n is None:
        return "N/A"
    if isinstance(n, float):
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.2f}"
    return f"{int(n):,}"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "$N/A"
    return f"${_fmt_num(float(n))}"


def _fmt_rate(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    return f"{n:.2f}%"


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("AB_TEST_START_DATE должен быть в формате YYYY-MM-DD")


def _required(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} обязателен при AB_TEST_REPORT_ENABLED=true")
    return value


def get_ab_test_config() -> AbTestConfig:
    enabled = is_ab_test_report_enabled()
    if not enabled:
        return AbTestConfig(
            enabled=False,
            app_index=1,
            app_name="",
            test_name="",
            start_date=date.today(),
            variant_a=AbTestVariantConfig("", "", ""),
            variant_b=AbTestVariantConfig("", "", ""),
        )

    test_name = _required(get_ab_test_name(), "AB_TEST_NAME")
    start_date = _parse_date(_required(get_ab_test_start_date(), "AB_TEST_START_DATE"))

    def variant_config(variant: str, default_label: str) -> AbTestVariantConfig:
        label = get_ab_test_variant_value(variant, "LABEL") or default_label
        paywall_id = _required(
            get_ab_test_variant_value(variant, "PAYWALL_ID"),
            f"AB_TEST_VARIANT_{variant}_PAYWALL_ID",
        )
        paywall_name = (
            get_ab_test_variant_value(variant, "PAYWALL_NAME")
            or label
        )
        return AbTestVariantConfig(label=label, paywall_id=paywall_id, paywall_name=paywall_name)

    app_index = get_ab_test_app_index()
    apps = get_adapty_apps()
    if app_index > len(apps):
        raise ValueError(
            f"AB_TEST_APP_INDEX={app_index} не найден: настроено приложений {len(apps)}"
        )

    return AbTestConfig(
        enabled=True,
        app_index=app_index,
        app_name=apps[app_index - 1].name,
        test_name=test_name,
        start_date=start_date,
        variant_a=variant_config("A", "Variant A"),
        variant_b=variant_config("B", "Variant B"),
    )


def _post_adapty(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    body: dict[str, Any],
) -> Optional[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        logger.debug("Adapty A/B response: status=%s body=%s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Adapty A/B API request failed: %s", e)
        return None
    except ValueError as e:
        logger.warning("Adapty A/B API invalid JSON: %s", e)
        return None
    return data if isinstance(data, dict) else None


def _value_from_metric(metric: Any, as_float: bool) -> Union[float, int, None]:
    if not isinstance(metric, dict):
        return None
    val = metric.get("value")
    if val is not None:
        try:
            return float(val) if as_float else int(float(val))
        except (TypeError, ValueError):
            pass
    points = metric.get("data")
    if isinstance(points, list) and points:
        total = 0.0
        has_values = False
        for point in points:
            if not isinstance(point, dict):
                continue
            point_val = point.get("value")
            if point_val is None and isinstance(point.get("values"), list):
                for nested in point["values"]:
                    if isinstance(nested, dict) and nested.get("y") is not None:
                        try:
                            total += float(nested["y"])
                            has_values = True
                        except (TypeError, ValueError):
                            continue
            elif point_val is not None:
                try:
                    total += float(point_val)
                    has_values = True
                except (TypeError, ValueError):
                    continue
        if has_values:
            return float(total) if as_float else int(total)
    return None


def _extract_revenue(data: Optional[dict[str, Any]]) -> Optional[float]:
    if not data:
        return None
    data_obj = data.get("data") or {}
    if not isinstance(data_obj, dict):
        return None
    for key in ("revenue", "gross_revenue", "proceeds"):
        val = _value_from_metric(data_obj.get(key), as_float=True)
        if val is not None:
            return float(val)
    logger.warning("A/B revenue metric not found, data keys=%s", list(data_obj.keys()))
    return None


def _fetch_variant_revenue(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    paywall_id: str,
    start_date: date,
    end_date: date,
) -> Optional[float]:
    data = _post_adapty(
        api_key,
        base_url,
        path,
        timezone,
        {
            "chart_id": "revenue",
            "filters": {
                "date": [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
                "paywall_id": [paywall_id],
            },
            "period_unit": "day",
            "format": "json",
        },
    )
    return _extract_revenue(data)


def _float_value(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_arpas(data: Optional[dict[str, Any]]) -> Optional[float]:
    if not data:
        return None
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        return None

    for row in rows:
        if isinstance(row, dict) and row.get("type") == "total":
            val = _float_value(row.get("total_arpas_usd"))
            if val is not None:
                return val

    first_row = rows[0]
    if isinstance(first_row, dict):
        val = _float_value(first_row.get("total_arpas_usd"))
        if val is not None:
            return val

    for row in rows:
        if not isinstance(row, dict):
            continue
        values = row.get("values")
        if not isinstance(values, list):
            continue
        for value in reversed(values):
            if not isinstance(value, dict):
                continue
            val = _float_value(value.get("arpas_usd"))
            if val is not None:
                return val
    return None


def _fetch_variant_arpas(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    paywall_id: str,
    start_date: date,
    end_date: date,
) -> Optional[float]:
    data = _post_adapty(
        api_key,
        base_url,
        path,
        timezone,
        {
            "filters": {
                "date": [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
                "paywall_id": [paywall_id],
            },
            "period_unit": "day",
            "period_type": "days",
            "value_type": "absolute",
            "value_field": "arpas",
            "accounting_type": "revenue",
            "format": "json",
        },
    )
    return _extract_arpas(data)


def _extract_funnel_metrics(data: Optional[dict[str, Any]]) -> tuple[Optional[int], Optional[int]]:
    if not data:
        return None, None
    rows = data.get("data")
    if not isinstance(rows, list):
        return None, None

    values: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_values = row.get("values")
        if isinstance(row_values, list):
            values.extend(v for v in row_values if isinstance(v, dict))

    paywall_views: Optional[int] = None
    purchases: Optional[int] = None
    for value in values:
        title = str(value.get("title", "")).strip().lower()
        raw_value = value.get("value")
        try:
            metric_value = int(float(raw_value))
        except (TypeError, ValueError):
            continue

        if paywall_views is None and "paywall" in title and (
            "display" in title or "view" in title or "shown" in title
        ):
            paywall_views = metric_value
        if purchases is None and (
            "purchase" in title or title in ("paid", "subscription")
        ):
            purchases = metric_value

    if purchases is None:
        logger.warning("A/B funnel purchases stage not found")
    return paywall_views, purchases


def _fetch_variant_funnel(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    paywall_id: str,
    start_date: date,
    end_date: date,
) -> tuple[Optional[int], Optional[int]]:
    data = _post_adapty(
        api_key,
        base_url,
        path,
        timezone,
        {
            "filters": {
                "date": [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
                "paywall_id": [paywall_id],
            },
            "period_unit": "day",
            "show_value_as": "absolute",
            "format": "json",
        },
    )
    return _extract_funnel_metrics(data)


def fetch_ab_test_metrics(
    config: AbTestConfig,
    report_date: date,
) -> list[AbTestVariantMetrics]:
    apps = get_adapty_apps()
    app_index = config.app_index - 1
    if app_index >= len(apps):
        raise ValueError(
            f"AB_TEST_APP_INDEX={config.app_index} не найден: настроено приложений {len(apps)}"
        )
    app = apps[app_index]
    base_url = get_adapty_base_url()
    analytics_path = get_adapty_analytics_path()
    cohort_path = get_adapty_cohort_path()
    funnel_path = get_adapty_funnel_path()
    timezone = get_adapty_timezone()

    rows: list[AbTestVariantMetrics] = []
    for variant in (config.variant_a, config.variant_b):
        revenue = _fetch_variant_revenue(
            app.api_key,
            base_url,
            analytics_path,
            timezone,
            variant.paywall_id,
            config.start_date,
            report_date,
        )
        arpas = _fetch_variant_arpas(
            app.api_key,
            base_url,
            cohort_path,
            timezone,
            variant.paywall_id,
            config.start_date,
            report_date,
        )
        paywall_views, purchases = _fetch_variant_funnel(
            app.api_key,
            base_url,
            funnel_path,
            timezone,
            variant.paywall_id,
            config.start_date,
            report_date,
        )
        rows.append(
            AbTestVariantMetrics(
                label=variant.label,
                paywall_name=variant.paywall_name,
                revenue=revenue,
                paywall_views=paywall_views,
                purchases=purchases,
                arpas=arpas,
            )
        )
    return rows


def _leader_line(rows: list[AbTestVariantMetrics]) -> str:
    if len(rows) != 2 or rows[0].revenue is None or rows[1].revenue is None:
        return "🏆 Лидер по revenue: N/A"
    first, second = rows
    if float(first.revenue) == float(second.revenue):
        return "🤝 Revenue equal"
    leader, runner_up = (first, second) if first.revenue > second.revenue else (second, first)
    delta = float(leader.revenue) - float(runner_up.revenue)
    return f"🏆 Лидер по revenue: {_escape_html(leader.label)} (+${_fmt_num(delta)})"


def build_ab_test_report(report_date: Optional[date] = None) -> Optional[str]:
    config = get_ab_test_config()
    if not config.enabled:
        return None
    if report_date is None:
        report_date = date.today()

    rows = fetch_ab_test_metrics(config, report_date)
    lines = [
        f"🧪 A/B Test: {_escape_html(config.test_name)}",
        f"📱 App: {_escape_html(config.app_name)}",
        "",
    ]
    for row in rows:
        lines.append(f"<b>{_escape_html(row.label)} / {_escape_html(row.paywall_name)}</b>")
        lines.append(f"💵 Revenue: {_fmt_money(row.revenue)}")
        lines.append(f"📈 ARPAS: {_fmt_money(row.arpas)}")
        lines.append(f"📲 Paywall views: {_fmt_num(row.paywall_views)}")
        lines.append(f"💳 Purchases: {_fmt_num(row.purchases)}")
        lines.append(f"🔄 CR view→purchase: {_fmt_rate(row.conversion_rate)}")
        lines.append("")
    lines.append(_leader_line(rows))
    return "\n".join(lines).strip()
