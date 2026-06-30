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
    get_adapty_apps,
    get_adapty_asa_api_base_url,
    get_adapty_dashboard_app_id,
    get_adapty_dashboard_company_id,
    get_adapty_dashboard_token,
    get_apple_ads_app_index,
    get_apple_ads_adam_id,
    get_apple_ads_api_base_url,
    get_apple_ads_attribution_source,
    get_apple_ads_client_id,
    get_apple_ads_internal_app_id,
    get_apple_ads_key_id,
    get_apple_ads_org_id,
    get_apple_ads_private_key,
    get_apple_ads_report_title,
    get_apple_ads_start_date,
    get_apple_ads_team_id,
    is_apple_ads_report_enabled,
)

logger = logging.getLogger(__name__)

ASA_BY_DAYS = [0, 3, 7, 14, 28, 31, 61, 92, 183, 366]


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
        if self.spend is None or self.revenue is None:
            return None
        if self.spend <= 0:
            return 0.0
        return (float(self.revenue) / float(self.spend)) * 100.0

    @property
    def cpi(self) -> Optional[float]:
        if self.spend is None or self.installs is None:
            return None
        if self.installs <= 0:
            return 0.0
        return float(self.spend) / float(self.installs)

    @property
    def cpa(self) -> Optional[float]:
        if self.spend is None or self.paid is None:
            return None
        if self.paid <= 0:
            return 0.0
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


def _date_filter(start_date: date, end_date: date) -> list[str]:
    return [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")]


def _asa_date_filters(config: AppleAdsReportConfig, report_date: date) -> dict[str, str]:
    return {
        "date_from": config.start_date.strftime("%Y-%m-%d"),
        "date_to": report_date.strftime("%Y-%m-%d"),
    }


def _asa_headers(token: str, company_id: str, app_id: str = "") -> dict[str, str]:
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {
        "Authorization": auth,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ADAPTY_DASHBOARD_COMPANY_ID": company_id,
    }
    if app_id:
        headers["ADAPTY_DASHBOARD_APP_ID"] = app_id
    return headers


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_scalar(value: Any) -> Optional[float]:
    direct = _number(value)
    if direct is not None:
        return direct

    if isinstance(value, dict):
        for key in ("amount", "value", "total", "common", "gross", "proceeds", "net"):
            if key in value:
                nested = _metric_scalar(value.get(key))
                if nested is not None:
                    return nested
        values = value.get("values")
        if isinstance(values, list):
            total = 0.0
            found = False
            for item in values:
                item_value = _metric_scalar(item)
                if item_value is not None:
                    total += item_value
                    found = True
            if found:
                return total
    return None


def _value_from_metric(metric: Any, as_float: bool) -> Optional[float]:
    if not isinstance(metric, dict):
        return None

    val = _metric_scalar(metric)
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
                direct = _metric_scalar(metric)
                if direct is not None:
                    return direct if as_float else float(int(direct))
                metric_value = _value_from_metric(metric, as_float=as_float)
                if metric_value is not None:
                    return metric_value

    for row in _walk_values(data):
        for key, value in row.items():
            if _normalize_key(str(key)) in normalized_aliases:
                direct = _metric_scalar(value)
                if direct is not None:
                    return direct if as_float else float(int(direct))
    return None


def _post_asa_json(
    token: str,
    company_id: str,
    app_id: str,
    base_url: str,
    path: str,
    body: dict[str, Any],
) -> Optional[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/{path.strip('/')}/"
    try:
        resp = requests.post(
            url,
            json=body,
            headers=_asa_headers(token, company_id, app_id),
            timeout=30,
        )
        logger.debug("Adapty ASA response: path=%s status=%s body=%s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("Adapty ASA request failed (path=%s): %s", path, e)
        return None
    except ValueError as e:
        logger.warning("Adapty ASA invalid JSON (path=%s): %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _extract_asa_metrics(data: Optional[dict[str, Any]]) -> dict[str, Optional[float]]:
    return {
        "spend": _extract_metric(
            data,
            (
                "performanceSpend",
                "performance_spend",
                "localSpend",
                "local_spend",
                "spend",
                "totalSpend",
                "total_spend",
            ),
            as_float=True,
        ),
        "revenue": _extract_metric(
            data,
            (
                "conversionsRevenue",
                "conversions_revenue",
                "grossRevenue",
                "gross_revenue",
                "revenue",
            ),
            as_float=True,
        ),
        "installs": _extract_metric(
            data,
            (
                "conversionsInstalls",
                "conversions_installs",
                "adaptyInstalls",
                "adapty_installs",
                "installs",
            ),
            as_float=False,
        ),
        "paid": _extract_metric(
            data,
            (
                "conversionsPaid",
                "conversions_paid",
                "paid",
                "subscriptions",
                "subscriptionsStarted",
                "subscriptions_started",
            ),
            as_float=False,
        ),
    }


def _asa_apps_info_bodies(config: AppleAdsReportConfig, report_date: date) -> list[dict[str, Any]]:
    date_range = _date_filter(config.start_date, report_date)
    date_filters = _asa_date_filters(config, report_date)
    return [
        {
            "filters": {
                "date": date_range,
                "pagination": {"number": 1, "size": 500},
                "include_outdated": True,
            }
        },
        {
            "filters": {
                **date_filters,
                "include_outdated": True,
            },
            "pagination": {"number": 1, "size": 500},
            "by_days": ASA_BY_DAYS,
        },
    ]


def _candidate_internal_id(row: dict[str, Any]) -> Optional[str]:
    for key in ("internalId", "internal_id", "appInternalId", "app_internal_id"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _row_matches_app(row: dict[str, Any], config: AppleAdsReportConfig, dashboard_app_id: str) -> bool:
    wanted = {_normalize_key(config.app_name), _normalize_key(config.report_title)}
    wanted.discard("")
    for key in ("id", "appId", "app_id", "adaptyAppId", "adapty_app_id"):
        if dashboard_app_id and str(row.get(key, "")) == dashboard_app_id:
            return True
    adam_id = get_apple_ads_adam_id()
    for key in ("adamId", "adam_id"):
        if adam_id and str(row.get(key, "")) == adam_id:
            return True
    for key in ("name", "title", "appName", "app_name"):
        normalized = _normalize_key(str(row.get(key, "")))
        if normalized and normalized in wanted:
            return True
    return False


def _find_asa_internal_app_id(
    data: Optional[dict[str, Any]],
    config: AppleAdsReportConfig,
    dashboard_app_id: str,
) -> Optional[str]:
    if not data:
        return None

    candidates: list[str] = []
    for row in _walk_values(data):
        nested_rows = [row]
        nested_app = row.get("app")
        if isinstance(nested_app, dict):
            nested_rows.append(nested_app)
        for item in nested_rows:
            internal_id = _candidate_internal_id(item)
            if internal_id and _row_matches_app(item, config, dashboard_app_id):
                return internal_id
            if internal_id:
                candidates.append(internal_id)

    unique_candidates = list(dict.fromkeys(candidates))
    return unique_candidates[0] if len(unique_candidates) == 1 else None


def _resolve_asa_internal_app_id(
    config: AppleAdsReportConfig,
    report_date: date,
    token: str,
    company_id: str,
    dashboard_app_id: str,
    base_url: str,
) -> Optional[str]:
    configured = get_apple_ads_internal_app_id()
    if configured:
        return configured

    for body in _asa_apps_info_bodies(config, report_date):
        data = _post_asa_json(token, company_id, dashboard_app_id, base_url, "asa-metadata/apps-info", body)
        internal_id = _find_asa_internal_app_id(data, config, dashboard_app_id)
        if internal_id:
            return internal_id
    logger.warning("Unable to resolve Adapty ASA internal app id for Apple Ads report")
    return None


def _fetch_adapty_asa_metrics(
    config: AppleAdsReportConfig,
    report_date: date,
) -> Optional[dict[str, Optional[float]]]:
    token = get_adapty_dashboard_token()
    company_id = get_adapty_dashboard_company_id()
    dashboard_app_id = get_adapty_dashboard_app_id()
    if not token or not company_id:
        logger.warning("Adapty ASA credentials are missing; Apple Ads report will be skipped")
        return None

    base_url = get_adapty_asa_api_base_url()
    internal_app_id = _resolve_asa_internal_app_id(
        config,
        report_date,
        token,
        company_id,
        dashboard_app_id,
        base_url,
    )
    if not internal_app_id:
        return None

    data = _post_asa_json(
        token,
        company_id,
        dashboard_app_id,
        base_url,
        "asa-metadata/v5/campaign/metrics/overview",
        {
            "filters": {
                **_asa_date_filters(config, report_date),
                "include_outdated": True,
                "deleted": False,
                "cohorts": [],
                "linked_app_internal_id": [internal_app_id],
            },
            "by_days": ASA_BY_DAYS,
            "profiles_counting_method": "profile_id",
            "period_unit": "day",
        },
    )
    metrics = _extract_asa_metrics(data)
    if any(value is not None for value in metrics.values()):
        return metrics
    logger.warning("Adapty ASA overview returned no Apple Ads metrics")
    return None


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
) -> Optional[AppleAdsMetrics]:
    apps = get_adapty_apps()
    _ = apps[config.app_index - 1]

    ads_metrics = _fetch_adapty_asa_metrics(config, report_date)
    if not ads_metrics:
        apple_totals = _fetch_apple_ads_campaign_totals(config, report_date)
        if not any(value is not None for value in apple_totals.values()):
            return None
        return AppleAdsMetrics(
            spend=(
                float(apple_totals["spend"])
                if apple_totals.get("spend") is not None
                else None
            ),
            revenue=None,
            installs=(
                int(apple_totals["installs"])
                if apple_totals.get("installs") is not None
                else None
            ),
            paid=None,
        )

    return AppleAdsMetrics(
        spend=float(ads_metrics["spend"]) if ads_metrics.get("spend") is not None else None,
        revenue=float(ads_metrics["revenue"]) if ads_metrics.get("revenue") is not None else None,
        installs=int(ads_metrics["installs"]) if ads_metrics.get("installs") is not None else None,
        paid=int(ads_metrics["paid"]) if ads_metrics.get("paid") is not None else None,
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

    title = _escape_html(config.report_title)
    metrics = fetch_apple_ads_metrics(config, report_date)
    if metrics is None:
        return "\n".join(
            [
                f"📣 Apple Ads — {title}",
                "Data unavailable. Check Adapty ASA / Apple Ads credentials in logs.",
            ]
        )
    return "\n".join(
        [
            f"📣 Apple Ads — {title}",
            f"Spend {_fmt_money(metrics.spend)} | Revenue {_fmt_money(metrics.revenue)} | ROAS {_fmt_rate(metrics.roas)}",
            f"Installs {_fmt_num(metrics.installs)} | Paid {_fmt_num(metrics.paid)} | CPI {_fmt_cost(metrics.cpi)} | CPA {_fmt_cost(metrics.cpa)}",
        ]
    )
