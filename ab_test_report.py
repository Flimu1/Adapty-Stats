"""Build a Telegram report from experiment-scoped Adapty A/B metrics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

from adapty_ab_dashboard import AdaptyAbDashboardClient
from config import (
    get_ab_test_app_index,
    get_ab_test_id,
    get_ab_test_name,
    get_ab_test_start_date,
    get_ab_test_variant_value,
    get_adapty_apps,
    get_adapty_dashboard_app_id,
    get_adapty_dashboard_token,
    get_adapty_timezone,
    is_ab_test_report_enabled,
)


@dataclass(frozen=True)
class AbTestVariantConfig:
    label: str
    paywall_id: str
    paywall_name: str


@dataclass(frozen=True)
class AbTestConfig:
    enabled: bool
    app_index: int
    app_name: str
    test_name: str
    start_date: date
    variant_a: AbTestVariantConfig
    variant_b: AbTestVariantConfig
    test_id: str = ""
    dashboard_app_id: str = ""
    dashboard_token: str = ""


@dataclass(frozen=True)
class AbTestVariantMetrics:
    label: str
    paywall_name: str
    revenue: Optional[float]
    paywall_views: Optional[int]
    purchases: Optional[int]
    arpas: Optional[float] = None
    revenue_per_1000: Optional[float] = None
    proceeds: Optional[float] = None
    net_revenue: Optional[float] = None
    probability: Optional[float] = None

    @property
    def conversion_rate(self) -> Optional[float]:
        if self.paywall_views is None or self.purchases is None or self.paywall_views <= 0:
            return None
        return (float(self.purchases) / float(self.paywall_views)) * 100.0


@dataclass(frozen=True)
class AbTestReportSnapshot:
    rows: list[AbTestVariantMetrics]
    collected_at: datetime


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
    return "$N/A" if n is None else f"${_fmt_num(float(n))}"


def _fmt_rate(n: Optional[float]) -> str:
    return "N/A" if n is None else f"{n:.2f}%"


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as err:
        raise ValueError("AB_TEST_START_DATE должен быть в формате YYYY-MM-DD") from err


def _required(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} обязателен при AB_TEST_REPORT_ENABLED=true")
    return value


def get_ab_test_config() -> AbTestConfig:
    if not is_ab_test_report_enabled():
        empty = AbTestVariantConfig("", "", "")
        return AbTestConfig(False, 1, "", "", date.today(), empty, empty)

    test_name = _required(get_ab_test_name(), "AB_TEST_NAME")
    test_id = _required(get_ab_test_id(), "AB_TEST_ID")
    dashboard_app_id = _required(
        get_adapty_dashboard_app_id(),
        "ADAPTY_DASHBOARD_APP_ID",
    )
    dashboard_token = _required(
        get_adapty_dashboard_token(),
        "ADAPTY_DASHBOARD_TOKEN",
    )
    start_date = _parse_date(_required(get_ab_test_start_date(), "AB_TEST_START_DATE"))

    def variant_config(variant: str) -> AbTestVariantConfig:
        label = get_ab_test_variant_value(variant, "LABEL") or variant
        if label != variant:
            raise ValueError(
                f"AB_TEST_VARIANT_{variant}_LABEL должен быть равен {variant}"
            )
        paywall_id = _required(
            get_ab_test_variant_value(variant, "PAYWALL_ID"),
            f"AB_TEST_VARIANT_{variant}_PAYWALL_ID",
        )
        paywall_name = _required(
            get_ab_test_variant_value(variant, "PAYWALL_NAME"),
            f"AB_TEST_VARIANT_{variant}_PAYWALL_NAME",
        )
        return AbTestVariantConfig(label, paywall_id, paywall_name)

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
        variant_a=variant_config("A"),
        variant_b=variant_config("B"),
        test_id=test_id,
        dashboard_app_id=dashboard_app_id,
        dashboard_token=dashboard_token,
    )


def fetch_ab_test_metrics(
    config: AbTestConfig,
    report_date: date,
) -> AbTestReportSnapshot:
    """Fetch one atomic, validated dashboard snapshot.

    ``report_date`` is retained for the scheduler interface; the Adapty A/B
    endpoint returns the test-to-date snapshot shown on the dashboard.
    """
    del report_date
    client = AdaptyAbDashboardClient(
        app_id=config.dashboard_app_id,
        token=config.dashboard_token,
    )
    result = client.fetch_metrics(
        test_id=config.test_id,
        expected_test_name=config.test_name,
        expected_variants={
            "A": (config.variant_a.paywall_id, config.variant_a.paywall_name),
            "B": (config.variant_b.paywall_id, config.variant_b.paywall_name),
        },
    )
    rows = [
        AbTestVariantMetrics(
            label=item.label,
            paywall_name=item.paywall_name,
            revenue=item.revenue,
            paywall_views=item.views,
            purchases=item.purchases,
            arpas=item.arpas,
            revenue_per_1000=item.revenue_per_1000,
            proceeds=item.proceeds,
            net_revenue=item.net_revenue,
            probability=item.probability,
        )
        for item in result.variants
    ]
    return AbTestReportSnapshot(rows=rows, collected_at=result.collected_at)


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
    effective_date = report_date or date.today()
    snapshot = fetch_ab_test_metrics(config, effective_date)
    timezone_name = get_adapty_timezone()
    collected_at = snapshot.collected_at.astimezone(ZoneInfo(timezone_name))

    lines = [
        f"🧪 A/B Test: {_escape_html(config.test_name)}",
        f"📱 App: {_escape_html(config.app_name)}",
        "🔎 Source: Adapty A/B Test Details",
        f"🕒 Snapshot: {collected_at.strftime('%d.%m.%Y %H:%M')} ({_escape_html(timezone_name)})",
        "",
    ]
    for row in snapshot.rows:
        lines.extend(
            [
                f"<b>{_escape_html(row.label)} / {_escape_html(row.paywall_name)}</b>",
                f"💵 Revenue: {_fmt_money(row.revenue)}",
                f"📊 Revenue per 1K users: {_fmt_money(row.revenue_per_1000)}",
                f"💰 Proceeds: {_fmt_money(row.proceeds)}",
                f"🏦 Net proceeds: {_fmt_money(row.net_revenue)}",
                f"🎯 P2BB: {_fmt_rate(row.probability)}",
                f"📈 ARPAS: {_fmt_money(row.arpas)}",
                f"📲 Paywall views: {_fmt_num(row.paywall_views)}",
                f"💳 Purchases: {_fmt_num(row.purchases)}",
                f"🔄 CR view→purchase: {_fmt_rate(row.conversion_rate)}",
                "",
            ]
        )
    lines.extend(
        [
            _leader_line(snapshot.rows),
            "ℹ️ Views обновляются Adapty периодически и могут отставать от revenue/purchases.",
        ]
    )
    return "\n".join(lines).strip()
