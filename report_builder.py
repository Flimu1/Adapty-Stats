"""
Сбор данных по всем приложениям, расчёт дельт, форматирование текста отчёта для Telegram.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Union
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
        inst_total = r.get("installs_total")
        inst_delta = r.get("installs_delta_24h")

        missing_fields: list[str] = []
        if mrr_total is None:
            missing_fields.append("MRR month")
        if mrr_delta is None:
            missing_fields.append("MRR delta")
        if inst_total is None:
            missing_fields.append("Installs month")
        if inst_delta is None:
            missing_fields.append("Installs day")
        if missing_fields:
            anomalies.append(f"{name}: отсутствуют поля ({', '.join(missing_fields)}).")

        if mrr_total is not None and mrr_total < 0:
            anomalies.append(f"{name}: MRR за месяц отрицательный ({mrr_total:.2f}).")
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
    return anomalies


def build_report(report_date: Union[date, datetime, None] = None) -> ReportBuildResult:
    """
    Запрашивает метрики у Adapty и формирует текст отчёта в формате:
    📊 Отчёт на ДД.ММ.ГГГГ
    **App Name**
    💰 MRR: $1,234 (+$56)   — за текущий месяц до даты отчёта и прирост за сутки
    📲 Installs: 5,678 (+120)  — установок за месяц до даты отчёта и прирост за сутки
    """
    try:
        tz = ZoneInfo(get_adapty_timezone())
    except Exception:
        tz = ZoneInfo("UTC")
    resolved_report_date = _resolve_report_date(report_date, tz)
    snapshot_time = datetime.now(tz).strftime("%H:%M")
    snapshot_tz = getattr(tz, "key", "Europe/Minsk")
    rows = fetch_all_metrics(report_date=resolved_report_date)
    anomalies = _detect_anomalies(rows)
    date_str = resolved_report_date.strftime("%d.%m.%Y")
    lines = [
        f"📊 Отчёт на {date_str}",
        f"🕒 Срез на {snapshot_time} ({snapshot_tz})",
        "",
        "<i>MRR, ARR — на дату. Revenue, Installs, Conv — за месяц. В скобках: Revenue — за сутки, MRR/ARR/Installs — дельта за сутки.</i>",
        "",
    ]
    if anomalies:
        lines.append("⚠️ <b>Обнаружены аномалии в данных, проверьте источники</b>")
        lines.append("")
    total_mrr = 0.0
    total_mrr_delta = 0.0
    total_inst_delta = 0
    total_revenue = 0.0
    total_revenue_per_day = 0.0
    total_arr = 0.0
    total_arr_delta = 0.0
    conv_weighted_sum = 0.0
    conv_weighted_installs = 0
    has_missing_data = False
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
        # Для сумм используем 0 если None, но помечаем что данные неполные
        if mrr_total is not None:
            total_mrr += mrr_total
        else:
            has_missing_data = True
        if revenue_total is None:
            has_missing_data = True
        if mrr_delta is not None:
            total_mrr_delta += mrr_delta
        if inst_delta is not None:
            total_inst_delta += inst_delta
        if revenue_total is not None:
            total_revenue += revenue_total
        if revenue_per_day is not None:
            total_revenue_per_day += revenue_per_day
        if arr_total is not None:
            total_arr += arr_total
        if arr_delta is not None:
            total_arr_delta += arr_delta
        if (
            conv_rate is not None
            and inst_total is not None
            and int(inst_total) > 0
        ):
            conv_weighted_sum += float(conv_rate) * int(inst_total)
            conv_weighted_installs += int(inst_total)
        if r.get("is_visible", True):
            lines.append(f"<b>{_escape_html(name)}</b>")
            lines.append(f"💰 MRR (на дату): ${_fmt_num(mrr_total)} {_fmt_delta(mrr_delta, is_mrr=True)}")
            lines.append(f"💵 Revenue (месяц): ${_fmt_num(revenue_total)} {_fmt_delta(revenue_per_day, is_mrr=True)}")
            lines.append(f"📲 Installs (месяц): {_fmt_num(inst_total)} {_fmt_delta(inst_delta)}")
            conv_str = f"{conv_rate:.2f}%" if conv_rate is not None else "N/A"
            lines.append(f"🔄 Conv. Install→Paid (месяц): {conv_str}")
            lines.append("")
    lines.append("<b>Total</b>")
    if has_missing_data:
        lines.append("⚠️ <i>Некоторые данные недоступны, сумма может быть неполной</i>")
    total_weighted_conv = (
        conv_weighted_sum / conv_weighted_installs
        if conv_weighted_installs > 0
        else None
    )
    total_conv_str = f"{total_weighted_conv:.2f}%" if total_weighted_conv is not None else "N/A"
    lines.append(f"💰 Total MRR (на дату): ${_fmt_num(total_mrr)} {_fmt_delta(total_mrr_delta, is_mrr=True)}")
    lines.append(f"📈 Total ARR (на дату): ${_fmt_num(total_arr)} {_fmt_delta(total_arr_delta, is_mrr=True)}")
    lines.append(f"💵 Total Revenue (месяц): ${_fmt_num(total_revenue)} {_fmt_delta(total_revenue_per_day, is_mrr=True)}")
    lines.append(f"📲 Total Downloads (за сутки): {_fmt_delta(total_inst_delta)}")
    lines.append(f"🔄 Total Conv. (месяц): {total_conv_str}")
    text = "\n".join(lines).strip()
    return ReportBuildResult(text=text, report_date=resolved_report_date, anomalies=anomalies)


def build_report_text(report_date: Union[date, datetime, None] = None) -> str:
    """Совместимость со старым API: возвращает только текст отчёта."""
    return build_report(report_date=report_date).text
