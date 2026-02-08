"""
Сбор данных по всем приложениям, расчёт дельт, форматирование текста отчёта для Telegram.
"""
from datetime import datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

from adapty_client import fetch_all_metrics
from config import get_timezone


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
        return f"({prefix}${_fmt_num(round(delta, 2))})"
    return f"({prefix}{_fmt_num(int(delta))})"


def _escape_html(text: str) -> str:
    """Экранирование HTML-символов для безопасной отправки в Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_report_text() -> str:
    """
    Запрашивает метрики у Adapty и формирует текст отчёта в формате:
    📊 Отчёт на ДД.ММ.ГГГГ
    **App Name**
    💰 MRR: $1,234 (+$56)   — за текущий месяц и прирост за сутки (календарные дни)
    📲 Installs: 5,678 (+120)  — установок за месяц и прирост за сутки
    """
    rows = fetch_all_metrics()
    try:
        tz = ZoneInfo(get_timezone())
    except Exception:
        tz = ZoneInfo("Europe/Minsk")
    date_str = datetime.now(tz).strftime("%d.%m.%Y")
    lines = [
        f"📊 Отчёт на {date_str}",
        "Данные за текущий месяц, в скобках — прирост за сутки.",
        "",
    ]
    total_mrr = 0.0
    total_mrr_delta = 0.0
    total_inst_delta = 0
    has_missing_data = False
    for r in rows:
        name = r.get("name", "App")
        mrr_total = r.get("mrr_total")
        mrr_delta = r.get("mrr_delta_24h")
        inst_total = r.get("installs_total")
        inst_delta = r.get("installs_delta_24h")
        # Для сумм используем 0 если None, но помечаем что данные неполные
        if mrr_total is not None:
            total_mrr += mrr_total
        else:
            has_missing_data = True
        if mrr_delta is not None:
            total_mrr_delta += mrr_delta
        if inst_delta is not None:
            total_inst_delta += inst_delta
        lines.append(f"<b>{_escape_html(name)}</b>")
        lines.append(f"💰 MRR: ${_fmt_num(mrr_total)} {_fmt_delta(mrr_delta, is_mrr=True)}")
        lines.append(f"📲 Installs: {_fmt_num(inst_total)} {_fmt_delta(inst_delta)}")
        lines.append("")
    lines.append("<b>Total</b>")
    if has_missing_data:
        lines.append("⚠️ <i>Некоторые данные недоступны, сумма может быть неполной</i>")
    lines.append(f"💰 Total MRR: ${_fmt_num(total_mrr)} {_fmt_delta(total_mrr_delta, is_mrr=True)}")
    lines.append(f"📲 Total Downloads (за сутки): {_fmt_delta(total_inst_delta)}")
    return "\n".join(lines).strip()
