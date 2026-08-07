"""
Сбор данных по всем приложениям, расчёт дельт, форматирование текста отчёта для Telegram.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

from adapty_client import fetch_all_metrics
from config import get_adapty_timezone


@dataclass
class ReportBuildResult:
    """Готовый отчёт + служебные данные для отправки и алертов."""

    text: str
    report_date: date
    anomalies: list[str]


def _fmt_num(n: Union[float, int, None]) -> str:
    """Форматирование числа с запятыми как разделителями тысяч (1,234)."""
    if n is None:
        return "N/A"
    if isinstance(n, float):
        if n == int(n):
            n = int(n)
        else:
            return f"{n:,.2f}"
    return f"{int(n):,}"


def _fmt_delta(delta: Union[float, None], is_mrr: bool = False) -> str:
    """Знак +/− и значение в скобках; для MRR — с символом $.
    При None возвращает (⚠️ N/A)."""
    if delta is None:
        return "(⚠️ N/A)"
    prefix = "+" if delta >= 0 else ""
    if is_mrr:
        rounded = round(float(delta), 2)
        sign = "+" if rounded >= 0 else "-"
        return f"({sign}${_fmt_num(abs(rounded))})"
    return f"({prefix}{_fmt_num(int(delta))})"


def _sum_complete(rows: list[dict], key: str) -> Optional[float]:
    """Sum a metric only when every displayed application supplied it."""
    values = [row.get(key) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(float(value) for value in values)


def _escape_html(text: str) -> str:
    """Экранирование HTML-символов для безопасной отправки в Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _resolve_report_date(
    report_date: Union[date, datetime, None],
    tz: ZoneInfo,
) -> date:
    """Дата отчёта: по умолчанию текущий день в timezone данных Adapty."""
    if report_date is None:
        return datetime.now(tz).date()
    if isinstance(report_date, datetime):
        return report_date.date()
    return report_date


def _detect_anomalies(rows: list[dict]) -> list[str]:
    """
    Базовые валидации данных перед отправкой отчёта.
    Держим только надёжные правила, чтобы не плодить ложные тревоги.
    """
    anomalies: list[str] = []
    for r in rows:
        name = str(r.get("name", "App"))
        mrr_total = r.get("mrr_total")
        mrr_delta = r.get("mrr_delta_24h")
        arr_total = r.get("arr_total")
        arr_delta = r.get("arr_delta_24h")
        revenue_total = r.get("revenue_total")
        revenue_day = r.get("revenue_per_day")
        inst_total = r.get("installs_total")
        inst_delta = r.get("installs_delta_24h")
        conv_rate = r.get("conv_rate")
        conv_from = r.get("conv_from")
        conv_to = r.get("conv_to")

        required_fields = (
            ("MRR", mrr_total),
            ("MRR delta", mrr_delta),
            ("ARR", arr_total),
            ("ARR delta", arr_delta),
            ("Revenue MTD", revenue_total),
            ("Revenue day", revenue_day),
            ("Installs MTD", inst_total),
            ("Installs day", inst_delta),
            ("Conversion", conv_rate),
            ("Conversion eligible", conv_from),
            ("Conversion paid", conv_to),
        )
        missing_fields = [label for label, value in required_fields if value is None]
        if missing_fields:
            msg = f"{name}: отсутствуют поля ({', '.join(missing_fields)})."
            if len(missing_fields) == len(required_fields):
                app_num = r.get("index", 0) + 1
                msg += f" Возможная причина: 401 Unauthorized — проверьте ADAPTY_API_KEY_APP{app_num}."
            anomalies.append(msg)

        if mrr_total is not None and mrr_total < 0:
            anomalies.append(f"{name}: MRR отрицательный ({mrr_total:.2f}).")
        if arr_total is not None and arr_total < 0:
            anomalies.append(f"{name}: ARR отрицательный ({arr_total:.2f}).")
        if revenue_total is not None and revenue_total < 0:
            anomalies.append(
                f"{name}: Revenue за месяц отрицательный ({revenue_total:.2f})."
            )
        if revenue_day is not None and revenue_day < 0:
            anomalies.append(
                f"{name}: Revenue за сутки отрицательный ({revenue_day:.2f})."
            )
        if inst_total is not None and inst_total < 0:
            anomalies.append(f"{name}: Installs за месяц отрицательные ({inst_total}).")
        if inst_delta is not None and inst_delta < 0:
            anomalies.append(f"{name}: Installs за сутки отрицательные ({inst_delta}).")
        if (
            inst_total is not None
            and inst_delta is not None
            and int(inst_delta) > int(inst_total)
        ):
            anomalies.append(
                f"{name}: installs за сутки ({inst_delta}) больше, чем MTD ({inst_total})."
            )
        if conv_rate is not None and not 0 <= conv_rate <= 100:
            anomalies.append(
                f"{name}: Conversion вне диапазона 0–100% ({conv_rate:.2f})."
            )
        if conv_from is not None and conv_from < 0:
            anomalies.append(
                f"{name}: eligible installs конверсии отрицательные ({conv_from})."
            )
        if conv_to is not None and conv_to < 0:
            anomalies.append(
                f"{name}: paid users конверсии отрицательные ({conv_to})."
            )
        if conv_from is not None and conv_to is not None and conv_to > conv_from:
            anomalies.append(
                f"{name}: paid users ({conv_to}) больше eligible installs ({conv_from})."
            )
    return anomalies


def build_report(report_date: Union[date, datetime, None] = None) -> ReportBuildResult:
    """
    Запрашивает метрики у Adapty и формирует текст отчёта в формате:
    📊 Отчёт на ДД.ММ.ГГГГ
    **App Name**
    💰 MRR: $1,234 (+$56) — текущая дневная точка и изменение к предыдущей
    📲 Installs: 5,678 (+120) — MTD summary и последняя дневная точка
    """
    try:
        tz = ZoneInfo(get_adapty_timezone())
    except Exception:
        tz = ZoneInfo("UTC")
    resolved_report_date = _resolve_report_date(report_date, tz)
    snapshot_time = datetime.now(tz).strftime("%H:%M")
    snapshot_tz = getattr(tz, "key", "Europe/Minsk")
    all_rows = fetch_all_metrics(report_date=resolved_report_date)
    rows = [row for row in all_rows if row.get("is_visible", True)]
    anomalies = _detect_anomalies(rows)
    date_str = resolved_report_date.strftime("%d.%m.%Y")
    lines = [
        f"📊 Отчёт на {date_str}",
        f"🕒 Срез на {snapshot_time} ({snapshot_tz})",
        "",
    ]
    if anomalies:
        lines.append("⚠️ <b>Обнаружены аномалии в данных, проверьте источники</b>")
        for anomaly in anomalies[:5]:
            detail = _escape_html(anomaly)
            if len(detail) > 300:
                detail = f"{detail[:297]}..."
            lines.append(f"• {detail}")
        if len(anomalies) > 5:
            lines.append(f"• Ещё аномалий: {len(anomalies) - 5}")
        lines.append("")
    total_mrr = _sum_complete(rows, "mrr_total")
    total_mrr_delta = _sum_complete(rows, "mrr_delta_24h")
    total_arr = _sum_complete(rows, "arr_total")
    total_arr_delta = _sum_complete(rows, "arr_delta_24h")
    total_revenue = _sum_complete(rows, "revenue_total")
    total_revenue_per_day = _sum_complete(rows, "revenue_per_day")
    total_inst_delta = _sum_complete(rows, "installs_delta_24h")
    total_conv_from = _sum_complete(rows, "conv_from")
    total_conv_to = _sum_complete(rows, "conv_to")
    total_conv = (
        total_conv_to / total_conv_from * 100
        if total_conv_from is not None
        and total_conv_to is not None
        and total_conv_from > 0
        else None
    )
    has_missing_data = any(
        value is None
        for value in (
            total_mrr,
            total_mrr_delta,
            total_arr,
            total_arr_delta,
            total_revenue,
            total_revenue_per_day,
            total_inst_delta,
            total_conv_from,
            total_conv_to,
        )
    )
    for r in rows:
        name = r.get("name", "App")
        mrr_total = r.get("mrr_total")
        mrr_delta = r.get("mrr_delta_24h")
        inst_total = r.get("installs_total")
        inst_delta = r.get("installs_delta_24h")
        revenue_total = r.get("revenue_total")
        revenue_per_day = r.get("revenue_per_day")
        arr_total = r.get("arr_total")
        arr_delta = r.get("arr_delta_24h")
        conv_rate = r.get("conv_rate")
        lines.append(f"<b>{_escape_html(name)}</b>")
        lines.append(
            f"💰 MRR (на дату): ${_fmt_num(mrr_total)} "
            f"{_fmt_delta(mrr_delta, is_mrr=True)}"
        )
        lines.append(
            f"💵 Revenue (месяц): ${_fmt_num(revenue_total)} "
            f"{_fmt_delta(revenue_per_day, is_mrr=True)}"
        )
        lines.append(
            f"📲 Installs (месяц): {_fmt_num(inst_total)} {_fmt_delta(inst_delta)}"
        )
        conv_str = f"{conv_rate:.2f}%" if conv_rate is not None else "N/A"
        lines.append(f"🔄 Conv. Install→Paid (месяц): {conv_str}")
        lines.append("")
    lines.append("<b>Total</b>")
    if has_missing_data:
        lines.append("⚠️ <i>Некоторые данные недоступны, сумма может быть неполной</i>")
    total_conv_str = f"{total_conv:.2f}%" if total_conv is not None else "N/A"
    lines.append(
        f"💰 Total MRR (на дату): ${_fmt_num(total_mrr)} "
        f"{_fmt_delta(total_mrr_delta, is_mrr=True)}"
    )
    lines.append(
        f"📈 Total ARR (на дату): ${_fmt_num(total_arr)} "
        f"{_fmt_delta(total_arr_delta, is_mrr=True)}"
    )
    lines.append(
        f"💵 Total Revenue (месяц): ${_fmt_num(total_revenue)} "
        f"{_fmt_delta(total_revenue_per_day, is_mrr=True)}"
    )
    lines.append(f"📲 Total Downloads (за сутки): {_fmt_delta(total_inst_delta)}")
    lines.append(f"🔄 Total Conv. (месяц): {total_conv_str}")
    text = "\n".join(lines).strip()
    return ReportBuildResult(text=text, report_date=resolved_report_date, anomalies=anomalies)


def build_report_text(report_date: Union[date, datetime, None] = None) -> str:
    """Совместимость со старым API: возвращает только текст отчёта."""
    return build_report(report_date=report_date).text
