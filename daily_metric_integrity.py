"""Validation, quarantine, and secret-free auditing for daily metrics."""

from datetime import date
import logging
import math
from typing import Any, Mapping, Optional, Sequence

from daily_report_contract import IntegrityIssue


logger = logging.getLogger(__name__)

MONETARY_FIELDS = (
    "mrr_total",
    "arr_total",
    "revenue_total",
    "revenue_per_day",
)
DELTA_FIELDS = ("mrr_delta_24h", "arr_delta_24h")
COUNT_FIELDS = (
    "installs_total",
    "installs_delta_24h",
    "conv_from",
    "conv_to",
)
REPORT_VALUE_FIELDS = (
    "mrr_total",
    "mrr_delta_24h",
    "arr_total",
    "arr_delta_24h",
    "revenue_total",
    "revenue_per_day",
    "installs_total",
    "installs_delta_24h",
    "conv_rate",
    "conv_from",
    "conv_to",
)


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _issue(row: Mapping[str, Any], code: str, metric: str, message: str) -> IntegrityIssue:
    return IntegrityIssue(
        code=code,
        message=message,
        app_name=str(row.get("name", "Unknown app")),
        metric=metric,
    )


def _quarantine(
    result: dict[str, Any],
    keys: tuple[str, ...],
    issue: IntegrityIssue,
) -> None:
    for key in keys:
        result[key] = None
    issues = list(result.get("issues", ()))
    identity = (issue.code, issue.app_name, issue.metric)
    if identity not in {
        (existing.code, existing.app_name, existing.metric)
        for existing in issues
    }:
        issues.append(issue)
    result["issues"] = tuple(issues)


def _is_exact_nonnegative_integer(value: Any) -> bool:
    parsed = _finite_number(value)
    return parsed is not None and parsed >= 0 and parsed.is_integer()


def validate_app_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Return a validated copy, replacing only untrusted fields with ``None``."""
    result = dict(row)
    result["issues"] = tuple(row.get("issues", ()))

    for field in MONETARY_FIELDS:
        parsed = _finite_number(result.get(field))
        if parsed is None or parsed < 0:
            _quarantine(
                result,
                (field,),
                _issue(row, f"{field}.invalid_value", field, f"{field} is not a finite non-negative number"),
            )

    for field in DELTA_FIELDS:
        if _finite_number(result.get(field)) is None:
            _quarantine(
                result,
                (field,),
                _issue(row, f"{field}.invalid_value", field, f"{field} is not a finite number"),
            )

    for field in COUNT_FIELDS:
        if not _is_exact_nonnegative_integer(result.get(field)):
            _quarantine(
                result,
                (field,),
                _issue(row, f"{field}.invalid_value", field, f"{field} is not a non-negative integer"),
            )

    conv_rate = _finite_number(result.get("conv_rate"))
    if conv_rate is None or not 0 <= conv_rate <= 100:
        _quarantine(
            result,
            ("conv_rate",),
            _issue(
                row,
                "conversion.invalid_rate",
                "conversion",
                "conversion rate is not a finite percentage between 0 and 100",
            ),
        )

    revenue_total = result.get("revenue_total")
    revenue_day = result.get("revenue_per_day")
    if revenue_total is not None and revenue_day is not None and revenue_day > revenue_total:
        _quarantine(
            result,
            ("revenue_total", "revenue_per_day"),
            _issue(
                row,
                "revenue.day_exceeds_mtd",
                "revenue",
                "report-day Revenue exceeds month-to-date Revenue",
            ),
        )

    installs_total = result.get("installs_total")
    installs_day = result.get("installs_delta_24h")
    if installs_total is not None and installs_day is not None and installs_day > installs_total:
        _quarantine(
            result,
            ("installs_total", "installs_delta_24h"),
            _issue(
                row,
                "installs.day_exceeds_mtd",
                "installs",
                "report-day Installs exceeds month-to-date Installs",
            ),
        )

    conv_from = result.get("conv_from")
    conv_to = result.get("conv_to")
    conv_rate = result.get("conv_rate")
    if conv_from is None or conv_to is None or conv_to > conv_from:
        _quarantine(
            result,
            ("conv_rate", "conv_from", "conv_to"),
            _issue(
                row,
                "conversion.invalid_counts",
                "conversion",
                "conversion counts are missing or inconsistent",
            ),
        )
    elif conv_rate is not None:
        expected_rate = 0.0 if conv_from == 0 else conv_to / conv_from * 100
        if abs(conv_rate - expected_rate) > 0.01:
            _quarantine(
                result,
                ("conv_rate", "conv_from", "conv_to"),
                _issue(
                    row,
                    "conversion.ratio_mismatch",
                    "conversion",
                    "conversion percentage does not match raw counts",
                ),
            )

    mrr_total = result.get("mrr_total")
    arr_total = result.get("arr_total")
    if mrr_total is not None and arr_total is not None and abs(arr_total - mrr_total * 12) > 0.05:
        _quarantine(
            result,
            ("arr_total",),
            _issue(
                row,
                "arr.mrr_multiple_mismatch",
                "arr_total",
                "ARR does not equal MRR multiplied by 12",
            ),
        )

    mrr_delta = result.get("mrr_delta_24h")
    arr_delta = result.get("arr_delta_24h")
    if mrr_delta is not None and arr_delta is not None and abs(arr_delta - mrr_delta * 12) > 0.05:
        _quarantine(
            result,
            ("arr_delta_24h",),
            _issue(
                row,
                "arr.mrr_delta_multiple_mismatch",
                "arr_delta_24h",
                "ARR delta does not equal MRR delta multiplied by 12",
            ),
        )

    return result


def count_integrity_problems(
    rows: Sequence[dict[str, Any]],
    portfolio_issues: Sequence[IntegrityIssue],
) -> int:
    identities = {
        (issue.code, issue.app_name, issue.metric)
        for issue in portfolio_issues
    }
    for row in rows:
        identities.update(
            (issue.code, issue.app_name, issue.metric)
            for issue in row.get("issues", ())
        )
    return len(identities)


def emit_integrity_audit(
    report_date: date,
    timezone: str,
    rows: Sequence[dict[str, Any]],
    total_status: Mapping[str, bool],
    portfolio_issues: Sequence[IntegrityIssue],
) -> None:
    """Log statuses and issue codes only; metric values and secrets are excluded."""
    for row in rows:
        issue_by_metric = {
            issue.metric: issue.code for issue in row.get("issues", ())
        }
        for metric in REPORT_VALUE_FIELDS:
            logger.info(
                "daily_metric_audit report_date=%s timezone=%s slot=%s app=%s metric=%s status=%s issue=%s",
                report_date.isoformat(),
                timezone,
                int(row["index"]) + 1,
                row["name"],
                metric,
                "valid" if row.get(metric) is not None else "invalid",
                issue_by_metric.get(metric, "none"),
            )

    for metric, is_valid in total_status.items():
        logger.info(
            "daily_total_audit report_date=%s timezone=%s total_metric=%s status=%s",
            report_date.isoformat(),
            timezone,
            metric,
            "valid" if is_valid else "invalid",
        )

    for issue in portfolio_issues:
        logger.warning(
            "daily_portfolio_audit report_date=%s timezone=%s issue=%s app=%s metric=%s",
            report_date.isoformat(),
            timezone,
            issue.code,
            issue.app_name or "portfolio",
            issue.metric or "configuration",
        )
