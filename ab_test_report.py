"""Build the strict Secret-Key Adapty A/B Telegram report."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Sequence

from adapty_ab_export import AdaptyAbExportClient, AdaptyAbVariantMetrics
from config import (
    get_ab_test_app_index,
    get_ab_test_id,
    get_ab_test_name,
    get_ab_test_start_date,
    get_ab_test_variant_value,
    get_adapty_analytics_path,
    get_adapty_apps,
    get_adapty_base_url,
    get_adapty_timezone,
    is_ab_test_report_enabled,
)


APPROVED_AB_APP_INDEX = 1
APPROVED_AB_APP_NAME = "Unfollowers: Follow & Unfollow"
APPROVED_AB_TEST_ID = "1db6e378-026f-4634-9522-ec4fa95deb99"
APPROVED_AB_TEST_NAME = "Test paywall prices. 4.99/29.99 vs 5.99/39.99"
APPROVED_AB_START_DATE = date(2026, 7, 10)
APPROVED_AB_VARIANT_A_LABEL = "A"
APPROVED_AB_VARIANT_A_PAYWALL_ID = "d6d24875-e330-4ad9-8ee0-841d3452a911"
APPROVED_AB_VARIANT_A_PAYWALL_NAME = "New Paywall Old Prices"
APPROVED_AB_VARIANT_B_LABEL = "B"
APPROVED_AB_VARIANT_B_PAYWALL_ID = "d6765d7f-eb06-42db-8d0d-ee21e2b41fe8"
APPROVED_AB_VARIANT_B_PAYWALL_NAME = "New Paywall New Prices"


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


APPROVED_AB_VARIANT_A = AbTestVariantConfig(
    APPROVED_AB_VARIANT_A_LABEL,
    APPROVED_AB_VARIANT_A_PAYWALL_ID,
    APPROVED_AB_VARIANT_A_PAYWALL_NAME,
)
APPROVED_AB_VARIANT_B = AbTestVariantConfig(
    APPROVED_AB_VARIANT_B_LABEL,
    APPROVED_AB_VARIANT_B_PAYWALL_ID,
    APPROVED_AB_VARIANT_B_PAYWALL_NAME,
)


def _validate_approved_ab_test_config(config: AbTestConfig) -> None:
    """Reject enabled configs that target anything but the approved experiment."""
    if not config.enabled:
        return
    if (
        config.app_index != APPROVED_AB_APP_INDEX
        or config.app_name != APPROVED_AB_APP_NAME
        or config.test_id != APPROVED_AB_TEST_ID
        or config.test_name != APPROVED_AB_TEST_NAME
        or config.start_date != APPROVED_AB_START_DATE
        or config.variant_a != APPROVED_AB_VARIANT_A
        or config.variant_b != APPROVED_AB_VARIANT_B
    ):
        raise ValueError(
            "A/B report configuration does not match the approved production experiment"
        )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_money(value: float) -> str:
    return f"${value:.2f}"


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

    def variant_config(variant: str) -> AbTestVariantConfig:
        label = _required(
            get_ab_test_variant_value(variant, "LABEL"),
            f"AB_TEST_VARIANT_{variant}_LABEL",
        )
        if label != variant:
            raise ValueError(f"AB_TEST_VARIANT_{variant}_LABEL должен быть равен {variant}")
        return AbTestVariantConfig(
            label=label,
            paywall_id=_required(
                get_ab_test_variant_value(variant, "PAYWALL_ID"),
                f"AB_TEST_VARIANT_{variant}_PAYWALL_ID",
            ),
            paywall_name=_required(
                get_ab_test_variant_value(variant, "PAYWALL_NAME"),
                f"AB_TEST_VARIANT_{variant}_PAYWALL_NAME",
            ),
        )

    app_index = get_ab_test_app_index()
    apps = get_adapty_apps()
    if app_index > len(apps):
        raise ValueError(
            f"AB_TEST_APP_INDEX={app_index} не найден: настроено приложений {len(apps)}"
        )
    app = apps[app_index - 1]
    if not app.api_key.strip():
        raise ValueError("Selected Adapty Secret API Key is required")

    variant_a = variant_config("A")
    variant_b = variant_config("B")
    if variant_a.paywall_id == variant_b.paywall_id:
        raise ValueError("A/B variants must use different paywall IDs")

    config = AbTestConfig(
        enabled=True,
        app_index=app_index,
        app_name=app.name,
        test_name=_required(get_ab_test_name(), "AB_TEST_NAME"),
        start_date=_parse_date(_required(get_ab_test_start_date(), "AB_TEST_START_DATE")),
        variant_a=variant_a,
        variant_b=variant_b,
        test_id=_required(get_ab_test_id(), "AB_TEST_ID"),
    )
    _validate_approved_ab_test_config(config)
    return config


def fetch_ab_test_metrics(
    config: AbTestConfig,
    report_date: date,
) -> list[AdaptyAbVariantMetrics]:
    """Collect exactly the configured A then B variants through the Secret API."""
    _validate_approved_ab_test_config(config)
    if report_date < config.start_date:
        raise ValueError("A/B report date cannot precede AB_TEST_START_DATE")
    apps = get_adapty_apps()
    if config.app_index < 1 or config.app_index > len(apps):
        raise ValueError("Selected Adapty app is not configured")
    app = apps[config.app_index - 1]
    if not app.api_key.strip():
        raise ValueError("Selected Adapty Secret API Key is required")

    client = AdaptyAbExportClient(
        api_key=app.api_key,
        base_url=get_adapty_base_url(),
        analytics_path=get_adapty_analytics_path(),
        timezone=get_adapty_timezone(),
    )
    rows = [
        client.fetch_variant(
            label=variant.label,
            paywall_id=variant.paywall_id,
            test_id=config.test_id,
            start_date=config.start_date,
            end_date=report_date,
        )
        for variant in (config.variant_a, config.variant_b)
    ]
    _validated_export_rows(rows, config)
    return rows


def _validated_export_rows(
    rows: Sequence[AdaptyAbVariantMetrics], config: AbTestConfig
) -> None:
    expected = (config.variant_a, config.variant_b)
    if len(rows) != 2:
        raise ValueError("A/B report requires exactly two complete rows")
    if [row.label for row in rows] != ["A", "B"]:
        raise ValueError("A/B Export rows must be ordered A then B")
    if [row.paywall_id for row in rows] != [variant.paywall_id for variant in expected]:
        raise ValueError("A/B Export rows do not match configured paywall IDs")
    if len({row.paywall_id for row in rows}) != 2:
        raise ValueError("A/B Export rows must have different paywall IDs")


def _leader_line(rows: Sequence[AdaptyAbVariantMetrics]) -> str:
    first, second = rows
    leader, runner_up = (first, second) if first.revenue >= second.revenue else (second, first)
    return f"🏆 Лидер по revenue: {leader.label} (+{_fmt_money(leader.revenue - runner_up.revenue)})"


def build_ab_test_report(report_date: Optional[date] = None) -> Optional[str]:
    config = get_ab_test_config()
    if not config.enabled:
        return None
    _validate_approved_ab_test_config(config)
    rows = fetch_ab_test_metrics(config, report_date or date.today())
    _validated_export_rows(rows, config)
    lines = [
        f"🧪 A/B Test: {_escape_html(config.test_name)}",
        f"📱 App: {_escape_html(config.app_name)}",
        "",
    ]
    for icon, row, variant in zip(
        ("🅰️", "🅱️"), rows, (config.variant_a, config.variant_b), strict=True
    ):
        lines.extend(
            [
                f"{icon} <b>{_escape_html(row.label)} / {_escape_html(variant.paywall_name)}</b>",
                f"💵 Revenue: {_fmt_money(row.revenue)}",
                f"📈 ARPAS: {_fmt_money(row.arpas)}",
                f"👥 Unique paywall views: {row.unique_views:,}",
                f"💳 Purchases: {row.purchases:,}",
                f"🔄 CR unique view→purchase: {row.conversion_rate:.2f}%",
                "",
            ]
        )
    lines.append(_leader_line(rows))
    return "\n".join(lines).strip()
