"""Build a canonical, integrity-aware daily Adapty report for Telegram."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Sequence, Union
from zoneinfo import ZoneInfo

from adapty_client import fetch_daily_snapshot
from config import get_adapty_timezone
from daily_metric_integrity import (
    count_integrity_problems,
    emit_integrity_audit,
)
from daily_report_contract import IntegrityIssue


@dataclass
class ReportBuildResult:
    """Rendered report together with safe details used by delivery alerts."""

    text: str
    report_date: date
    anomalies: list[str]
    integrity_problem_count: int = 0


def _fmt_num(n: Union[float, int, None]) -> str:
    if n is None:
        return "N/A"
    if isinstance(n, float):
        if n == int(n):
            n = int(n)
        else:
            return f"{n:,.2f}"
    return f"{int(n):,}"


def _fmt_delta(delta: Union[float, int, None], is_mrr: bool = False) -> str:
    if delta is None:
        return "(⚠️ N/A)"
    if is_mrr:
        rounded = round(float(delta), 2)
        sign = "+" if rounded >= 0 else "-"
        return f"({sign}${_fmt_num(abs(rounded))})"
    prefix = "+" if delta >= 0 else ""
    return f"({prefix}{_fmt_num(int(delta))})"


def _sum_complete(rows: Sequence[dict], key: str) -> Optional[float]:
    values = [row.get(key) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(float(value) for value in values)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _resolve_report_date(
    report_date: Union[date, datetime, None],
    tz: ZoneInfo,
) -> date:
    if report_date is None:
        return datetime.now(tz).date()
    if isinstance(report_date, datetime):
        return report_date.date()
    return report_date


def _issue_details(
    rows: Sequence[dict],
    portfolio_issues: Sequence[IntegrityIssue],
) -> list[str]:
    details: list[str] = []
    seen: set[tuple[str, Optional[str], Optional[str]]] = set()
    for issue in (
        *portfolio_issues,
        *(issue for row in rows for issue in row.get("issues", ())),
    ):
        identity = (issue.code, issue.app_name, issue.metric)
        if identity in seen:
            continue
        seen.add(identity)
        prefix = f"{issue.app_name}: " if issue.app_name else ""
        details.append(f"{prefix}{issue.message} [{issue.code}]")
    return details


def _total_conversion(rows: Sequence[dict]) -> Optional[float]:
    total_from = _sum_complete(rows, "conv_from")
    total_to = _sum_complete(rows, "conv_to")
    if total_from is None or total_to is None:
        return None
    if total_from == 0:
        return 0.0 if total_to == 0 else None
    return total_to / total_from * 100


def build_report(report_date: Union[date, datetime, None] = None) -> ReportBuildResult:
    """Collect one validated snapshot and render only trusted numeric fields."""
    try:
        tz = ZoneInfo(get_adapty_timezone())
    except Exception:
        tz = ZoneInfo("Europe/Minsk")
    resolved_report_date = _resolve_report_date(report_date, tz)
    snapshot_time = datetime.now(tz).strftime("%H:%M")
    snapshot_tz = getattr(tz, "key", "Europe/Minsk")

    snapshot = fetch_daily_snapshot(report_date=resolved_report_date)
    rows = list(snapshot.rows)
    anomalies = _issue_details(rows, snapshot.portfolio_issues)
    problem_count = count_integrity_problems(rows, snapshot.portfolio_issues)

    total_mrr = _sum_complete(rows, "mrr_total")
    total_mrr_delta = _sum_complete(rows, "mrr_delta_24h")
    total_arr = _sum_complete(rows, "arr_total")
    total_arr_delta = _sum_complete(rows, "arr_delta_24h")
    total_revenue = _sum_complete(rows, "revenue_total")
    total_revenue_per_day = _sum_complete(rows, "revenue_per_day")
    total_inst_delta = _sum_complete(rows, "installs_delta_24h")
    total_conv = _total_conversion(rows)

    lines = [
        f"📊 Отчёт на {resolved_report_date.strftime('%d.%m.%Y')}",
        f"🕒 Срез на {snapshot_time} ({snapshot_tz})",
        "",
    ]
    if anomalies:
        lines.append("⚠️ <b>Проверка данных обнаружила проблемы</b>")
        for anomaly in anomalies[:5]:
            detail = _escape_html(anomaly)
            if len(detail) > 300:
                detail = f"{detail[:297]}..."
            lines.append(f"• {detail}")
        if len(anomalies) > 5:
            lines.append(f"• Ещё проблем: {len(anomalies) - 5}")
        lines.append("")

    for row in rows:
        lines.append(f"<b>{_escape_html(str(row.get('name', 'App')))}</b>")
        lines.append(
            f"💰 MRR (на дату): ${_fmt_num(row.get('mrr_total'))} "
            f"{_fmt_delta(row.get('mrr_delta_24h'), is_mrr=True)}"
        )
        lines.append(
            f"💵 Revenue (месяц): ${_fmt_num(row.get('revenue_total'))} "
            f"{_fmt_delta(row.get('revenue_per_day'), is_mrr=True)}"
        )
        lines.append(
            f"📲 Installs (месяц): {_fmt_num(row.get('installs_total'))} "
            f"{_fmt_delta(row.get('installs_delta_24h'))}"
        )
        conv_rate = row.get("conv_rate")
        conv_text = f"{conv_rate:.2f}%" if conv_rate is not None else "N/A"
        lines.append(f"🔄 Conv. Install→Paid (месяц): {conv_text}")
        lines.append("")

    total_conv_text = f"{total_conv:.2f}%" if total_conv is not None else "N/A"
    lines.extend([
        "<b>Total</b>",
        (
            f"💰 Total MRR (на дату): ${_fmt_num(total_mrr)} "
            f"{_fmt_delta(total_mrr_delta, is_mrr=True)}"
        ),
        (
            f"📈 Total ARR (на дату): ${_fmt_num(total_arr)} "
            f"{_fmt_delta(total_arr_delta, is_mrr=True)}"
        ),
        (
            f"💵 Total Revenue (месяц): ${_fmt_num(total_revenue)} "
            f"{_fmt_delta(total_revenue_per_day, is_mrr=True)}"
        ),
        f"📲 Total Downloads (за сутки): {_fmt_delta(total_inst_delta)}",
        f"🔄 Total Conv. (месяц): {total_conv_text}",
        "",
    ])
    if problem_count:
        lines.append(
            f"⚠️ Проверка данных: обнаружено {problem_count} проблем — "
            "недостоверные метрики показаны как N/A"
        )
    else:
        lines.append("✅ Проверка данных: пройдена")

    emit_integrity_audit(
        report_date=resolved_report_date,
        timezone=snapshot_tz,
        rows=rows,
        total_status={
            "mrr_total": total_mrr is not None,
            "mrr_delta_24h": total_mrr_delta is not None,
            "arr_total": total_arr is not None,
            "arr_delta_24h": total_arr_delta is not None,
            "revenue_total": total_revenue is not None,
            "revenue_per_day": total_revenue_per_day is not None,
            "installs_delta_24h": total_inst_delta is not None,
            "conversion": total_conv is not None,
        },
        portfolio_issues=snapshot.portfolio_issues,
    )

    return ReportBuildResult(
        text="\n".join(lines).strip(),
        report_date=resolved_report_date,
        anomalies=anomalies,
        integrity_problem_count=problem_count,
    )


def build_report_text(report_date: Union[date, datetime, None] = None) -> str:
    return build_report(report_date=report_date).text
