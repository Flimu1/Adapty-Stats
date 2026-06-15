"""
Сбор и форматирование компактного Telegram-отчёта по Apple Ads.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
import time
from typing import Any, Optional

import requests

from config import (
    get_adapty_analytics_path,
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_timezone,
    get_apple_ads_app_index,
    get_apple_ads_adam_id,
    get_apple_ads_api_base_url,
    get_apple_ads_attribution_source,
    get_apple_ads_client_id,
    get_apple_ads_key_id,
    get_apple_ads_metrics_paths,
    get_apple_ads_org_id,
    get_apple_ads_private_key,
    get_apple_ads_report_title,
    get_apple_ads_start_date,
    get_apple_ads_team_id,
    is_apple_ads_report_enabled,
)

logger = logging.getLogger(__name__)


@dataclass
class AppleAdsReportConfig:
    enabled: bool
    app_index: int
    app_name: str
    report_title: str
    start_date: date
    attribution_source: str


@dataclass
class AppleAdsMetrics:
    spend: Optional[float]
    revenue: Optional[float]
    installs: Optional[int]
    paid: Optional[int]

    @property
    def roas(self) -> Optional[float]:
        if self.spend is None or self.revenue is None or self.spend <= 0:
            return None
        return (float(self.revenue) / float(self.spend)) * 100.0

    @property
    def cpi(self) -> Optional[float]:
        if self.spend is None or self.installs is None or self.installs <= 0:
            return None
        return float(self.spend) / float(self.installs)

    @property
    def cpa(self) -> Optional[float]:
        if self.spend is None or self.paid is None or self.paid <= 0:
            return None
        return float(self.spend) / float(self.paid)


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("APPLE_ADS_START_DATE должен быть в формате YYYY-MM-DD")


def get_apple_ads_report_config() -> AppleAdsReportConfig:
    enabled = is_apple_ads_report_enabled()
    if not enabled:
        return AppleAdsReportConfig(
            enabled=False,
            app_index=1,
            app_name="",
            report_title=get_apple_ads_report_title(),
            start_date=date.today(),
            attribution_source=get_apple_ads_attribution_source(),
        )

    raw_start_date = get_apple_ads_start_date()
    if not raw_start_date:
        raise ValueError("APPLE_ADS_START_DATE обязателен при APPLE_ADS_REPORT_ENABLED=true")

    app_index = get_apple_ads_app_index()
    apps = get_adapty_apps()
    if app_index > len(apps):
        raise ValueError(
            f"APPLE_ADS_APP_INDEX={app_index} не найден: настроено приложений {len(apps)}"
        )

    return AppleAdsReportConfig(
        enabled=True,
        app_index=app_index,
        app_name=apps[app_index - 1].name,
        report_title=get_apple_ads_report_title(),
        start_date=_parse_date(raw_start_date),
        attribution_source=get_apple_ads_attribution_source(),
    )


def _headers(api_key: str, timezone: str) -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "Adapty-Tz": timezone,
    }


def _date_filter(start_date: date, end_date: date) -> list[str]:
    return [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")]


def _filters(config: AppleAdsReportConfig, report_date: date) -> dict[str, Any]:
    filters: dict[str, Any] = {"date": _date_filter(config.start_date, report_date)}
    if config.attribution_source:
        filters["attribution_source"] = [config.attribution_source]
    return filters


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value_from_metric(metric: Any, as_float: bool) -> Optional[float]:
    if not isinstance(metric, dict):
        return None

    val = _number(metric.get("value"))
    if val is not None:
        return val if as_float else float(int(val))

    total = 0.0
    found = False
    points = metric.get("data")
    if isinstance(points, list):
        for point in points:
            if not isinstance(point, dict):
                continue
            point_val = _number(point.get("value"))
            if point_val is not None:
                total += point_val
                found = True
                continue
            values = point.get("values")
            if isinstance(values, list):
                for nested in values:
                    if isinstance(nested, dict):
                        nested_val = _number(nested.get("y") or nested.get("value"))
                        if nested_val is not None:
                            total += nested_val
                            found = True
    if found:
        return total if as_float else float(int(total))
    return None


def _walk_values(data: Any):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _walk_values(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_values(item)


def _extract_metric(data: Optional[dict[str, Any]], aliases: tuple[str, ...], as_float: bool) -> Optional[float]:
    if not data:
        return None
    normalized_aliases = {_normalize_key(alias) for alias in aliases}
    data_obj = data.get("data") if isinstance(data, dict) else None

    search_roots = []
    if isinstance(data_obj, dict):
        search_roots.append(data_obj)
    search_roots.append(data)

    for root in search_roots:
        if not isinstance(root, dict):
            continue
        for key, metric in root.items():
            if _normalize_key(str(key)) in normalized_aliases:
                direct = _number(metric)
                if direct is not None:
                    return direct if as_float else float(int(direct))
                metric_value = _value_from_metric(metric, as_float=as_float)
                if metric_value is not None:
                    return metric_value

    for row in _walk_values(data):
        for key, value in row.items():
            if _normalize_key(str(key)) in normalized_aliases:
                direct = _number(value)
                if direct is not None:
                    return direct if as_float else float(int(direct))
    return None


def _post_json(
    api_key: str,
    base_url: str,
    path: str,
    timezone: str,
    body: dict[str, Any],
) -> Optional[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        resp = requests.post(url, json=body, headers=_headers(api_key, timezone), timeout=30)
        logger.debug("Apple Ads API response: path=%s status=%s body=%s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Apple Ads API request failed (path=%s): %s", path, e)
        return None
    except ValueError as e:
        logger.warning("Apple Ads API invalid JSON (path=%s): %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _fetch_analytics_chart(
    api_key: str,
    base_url: str,
    analytics_path: str,
    timezone: str,
    config: AppleAdsReportConfig,
    report_date: date,
    chart_id: str,
    aliases: tuple[str, ...],
    as_float: bool,
) -> Optional[float]:
    data = _post_json(
        api_key,
        base_url,
        analytics_path,
        timezone,
        {
            "chart_id": chart_id,
            "filters": _filters(config, report_date),
            "period_unit": "day",
            "date_type": "profile_install_date",
            "format": "json",
        },
    )
    return _extract_metric(data, aliases, as_float=as_float)


def _fetch_ads_manager_metrics(
    api_key: str,
    base_url: str,
    timezone: str,
    config: AppleAdsReportConfig,
    report_date: date,
) -> dict[str, Optional[float]]:
    body = {
        "filters": _filters(config, report_date),
        "period_unit": "day",
        "format": "json",
        "metrics": ["spend", "revenue", "installs", "subscriptions"],
    }
    for path in get_apple_ads_metrics_paths():
        data = _post_json(api_key, base_url, path, timezone, body)
        if not data:
            continue
        spend = _extract_metric(data, ("spend", "cost", "ad_spend", "total_spend"), as_float=True)
        revenue = _extract_metric(data, ("revenue", "gross_revenue", "total_revenue"), as_float=True)
        installs = _extract_metric(data, ("installs", "install", "total_installs"), as_float=False)
        paid = _extract_metric(
            data,
            ("paid", "subscriptions", "subscriptions_new", "cost_per_subscription_count"),
            as_float=False,
        )
        if any(v is not None for v in (spend, revenue, installs, paid)):
            return {
                "spend": spend,
                "revenue": revenue,
                "installs": installs,
                "paid": paid,
            }
    return {"spend": None, "revenue": None, "installs": None, "paid": None}


def _apple_ads_credentials() -> Optional[dict[str, str]]:
    creds = {
        "client_id": get_apple_ads_client_id(),
        "team_id": get_apple_ads_team_id(),
        "key_id": get_apple_ads_key_id(),
        "private_key": get_apple_ads_private_key(),
        "org_id": get_apple_ads_org_id(),
        "adam_id": get_apple_ads_adam_id(),
        "base_url": get_apple_ads_api_base_url(),
    }
    required = ("client_id", "team_id", "key_id", "private_key", "org_id")
    if not all(creds[key] for key in required):
        return None
    return creds


def _build_apple_ads_client_secret(creds: dict[str, str]) -> str:
    import jwt

    now = int(time.time())
    payload = {
        "iss": creds["team_id"],
        "sub": creds["client_id"],
        "aud": "https://appleid.apple.com",
        "iat": now,
        "exp": now + 3600,
    }
    headers = {"kid": creds["key_id"], "alg": "ES256"}
    return jwt.encode(payload, creds["private_key"], algorithm="ES256", headers=headers)


def _fetch_apple_ads_access_token(creds: dict[str, str]) -> Optional[str]:
    try:
        client_secret = _build_apple_ads_client_secret(creds)
        resp = requests.post(
            "https://appleid.apple.com/auth/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": creds["client_id"],
                "client_secret": client_secret,
                "scope": "searchadsorg",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Apple Ads OAuth token request failed: %s", e)
        return None
    token = data.get("access_token") if isinstance(data, dict) else None
    return str(token) if token else None


def _apple_ads_report_body(config: AppleAdsReportConfig, report_date: date, adam_id: str) -> dict[str, Any]:
    conditions = []
    if adam_id:
        conditions.append(
            {
                "field": "adamId",
                "operator": "EQUALS",
                "values": [adam_id],
            }
        )
    return {
        "startTime": config.start_date.strftime("%Y-%m-%d"),
        "endTime": report_date.strftime("%Y-%m-%d"),
        "selector": {
            "orderBy": [{"field": "campaignId", "sortOrder": "ASCENDING"}],
            "pagination": {"offset": 0, "limit": 1000},
            "conditions": conditions,
        },
        "timeZone": "UTC",
        "returnRowTotals": True,
        "returnGrandTotals": True,
        "returnRecordsWithNoMetrics": False,
    }


def _extract_money_value(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key in ("amount", "value"):
            parsed = _number(value.get(key))
            if parsed is not None:
                return parsed
    return _number(value)


def _extract_apple_report_totals(data: Optional[dict[str, Any]]) -> dict[str, Optional[float]]:
    if not data:
        return {"spend": None, "installs": None}

    spend: Optional[float] = None
    installs: Optional[float] = None
    total_rows: list[dict[str, Any]] = []
    for row in _walk_values(data):
        row_type = _normalize_key(str(row.get("type", "")))
        if row_type in ("grandtotals", "grandtotal", "total"):
            total_rows.append(row)
        if "grandTotals" in row and isinstance(row["grandTotals"], dict):
            total_rows.append(row["grandTotals"])
        if "total" in row and isinstance(row["total"], dict):
            total_rows.append(row["total"])

    if not total_rows:
        total_rows = [row for row in _walk_values(data) if isinstance(row, dict)]

    for row in total_rows:
        if spend is None:
            for key in ("localSpend", "spend", "totalSpend"):
                if key in row:
                    spend = _extract_money_value(row.get(key))
                    if spend is not None:
                        break
        if installs is None:
            for key in ("installs", "totalInstalls", "downloads", "totalDownloads"):
                if key in row:
                    installs = _number(row.get(key))
                    if installs is not None:
                        break
        if spend is not None and installs is not None:
            break
    return {"spend": spend, "installs": installs}


def _fetch_apple_ads_campaign_totals(
    config: AppleAdsReportConfig,
    report_date: date,
) -> dict[str, Optional[float]]:
    creds = _apple_ads_credentials()
    if not creds:
        return {"spend": None, "installs": None}

    token = _fetch_apple_ads_access_token(creds)
    if not token:
        return {"spend": None, "installs": None}

    url = f"{creds['base_url']}/reports/campaigns"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-AP-Context": f"orgId={creds['org_id']}",
    }
    try:
        resp = requests.post(
            url,
            json=_apple_ads_report_body(config, report_date, creds.get("adam_id", "")),
            headers=headers,
            timeout=30,
        )
        logger.debug("Apple Ads campaign report response: status=%s body=%s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Apple Ads campaign report request failed: %s", e)
        return {"spend": None, "installs": None}
    except ValueError as e:
        logger.warning("Apple Ads campaign report invalid JSON: %s", e)
        return {"spend": None, "installs": None}
    return _extract_apple_report_totals(data if isinstance(data, dict) else None)


def fetch_apple_ads_metrics(
    config: AppleAdsReportConfig,
    report_date: date,
) -> AppleAdsMetrics:
    apps = get_adapty_apps()
    app = apps[config.app_index - 1]
    base_url = get_adapty_base_url()
    analytics_path = get_adapty_analytics_path()
    timezone = get_adapty_timezone()

    ads_metrics = _fetch_ads_manager_metrics(app.api_key, base_url, timezone, config, report_date)
    apple_totals = (
        _fetch_apple_ads_campaign_totals(config, report_date)
        if ads_metrics.get("spend") is None
        else {"spend": None, "installs": None}
    )

    revenue = ads_metrics.get("revenue")
    if revenue is None:
        revenue = _fetch_analytics_chart(
            app.api_key,
            base_url,
            analytics_path,
            timezone,
            config,
            report_date,
            "revenue",
            ("revenue", "gross_revenue", "proceeds"),
            as_float=True,
        )

    installs = ads_metrics.get("installs")
    if installs is None:
        installs = _fetch_analytics_chart(
            app.api_key,
            base_url,
            analytics_path,
            timezone,
            config,
            report_date,
            "installs",
            ("common", "installs", "new_installs"),
            as_float=False,
        )
    if installs is None:
        installs = apple_totals.get("installs")

    paid = ads_metrics.get("paid")
    if paid is None:
        paid = _fetch_analytics_chart(
            app.api_key,
            base_url,
            analytics_path,
            timezone,
            config,
            report_date,
            "subscriptions_new",
            ("subscriptions", "subscriptions_new", "common"),
            as_float=False,
        )

    return AppleAdsMetrics(
        spend=ads_metrics.get("spend") if ads_metrics.get("spend") is not None else apple_totals.get("spend"),
        revenue=float(revenue) if revenue is not None else None,
        installs=int(installs) if installs is not None else None,
        paid=int(paid) if paid is not None else None,
    )


def _fmt_num(n: Optional[int]) -> str:
    if n is None:
        return "N/A"
    return f"{int(n):,}"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "$N/A"
    amount = float(n)
    if amount == int(amount):
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _fmt_cost(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    return _fmt_money(n)


def _fmt_rate(n: Optional[float]) -> str:
    if n is None:
        return "N/A"
    return f"{float(n):.0f}%"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_apple_ads_report(report_date: Optional[date] = None) -> Optional[str]:
    config = get_apple_ads_report_config()
    if not config.enabled:
        return None
    if report_date is None:
        report_date = date.today()

    metrics = fetch_apple_ads_metrics(config, report_date)
    title = _escape_html(config.report_title)
    return "\n".join(
        [
            f"📣 Apple Ads — {title}",
            f"Spend {_fmt_money(metrics.spend)} | Revenue {_fmt_money(metrics.revenue)} | ROAS {_fmt_rate(metrics.roas)}",
            f"Installs {_fmt_num(metrics.installs)} | Paid {_fmt_num(metrics.paid)} | CPI {_fmt_cost(metrics.cpi)} | CPA {_fmt_cost(metrics.cpa)}",
        ]
    )
