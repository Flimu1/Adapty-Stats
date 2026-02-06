"""
Сбор данных по всем приложениям, расчёт дельт, форматирование текста отчёта для Telegram.
"""
from datetime import datetime
from typing import Union

from adapty_client import fetch_all_metrics


def _fmt_num(n: Union[float, int]) -> str:
    """Форматирование числа с запятыми как разделителями тысяч (1,234)."""
    if isinstance(n, float):
        if n == int(n):
            n = int(n)
        else:
            return f"{n:,.2f}"
    return f"{int(n):,}"


def _fmt_delta(delta: float, is_mrr: bool = False) -> str:
    """Знак +/− и значение в скобках; для MRR — с символом $."""
    prefix = "+" if delta >= 0 else ""
    if is_mrr:
        return f"({prefix}${_fmt_num(round(delta, 2))})"
    return f"({prefix}{_fmt_num(int(delta))})"


def build_report_text() -> str:
    """
    Запрашивает метрики у Adapty и формирует текст отчёта в формате:
    📊 Отчёт на ДД.ММ.ГГГГ
    **App Name**
    💰 MRR: $1,234 (+$56)
    📲 Installs: 5,678 (+120)
    """
    rows = fetch_all_metrics()
    date_str = datetime.now().strftime("%d.%m.%Y")
    lines = [f"📊 Отчёт на {date_str}", ""]
    for r in rows:
        name = r.get("name", "App")
        mrr_total = r.get("mrr_total") or 0
        mrr_delta = r.get("mrr_delta_24h") or 0
        inst_total = r.get("installs_total") or 0
        inst_delta = r.get("installs_delta_24h") or 0
        lines.append(f"**{name}**")
        lines.append(f"💰 MRR: ${_fmt_num(mrr_total)} {_fmt_delta(mrr_delta, is_mrr=True)}")
        lines.append(f"📲 Installs: {_fmt_num(inst_total)} {_fmt_delta(inst_delta)}")
        lines.append("")
    return "\n".join(lines).strip()
