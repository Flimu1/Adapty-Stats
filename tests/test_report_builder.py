"""Regression tests for canonical, integrity-aware Telegram report rendering."""

from datetime import date
import unittest
from unittest.mock import patch

from daily_report_contract import (
    CANONICAL_APP_NAMES,
    DailyMetricsSnapshot,
    IntegrityIssue,
)


def valid_rows() -> list[dict]:
    rows: list[dict] = []
    for index, name in enumerate(CANONICAL_APP_NAMES, start=1):
        mrr = float(index * 100)
        conv_from = 100 * index
        conv_to = index
        rows.append({
            "index": index - 1,
            "name": name,
            "mrr_total": mrr,
            "mrr_delta_24h": float(index),
            "arr_total": mrr * 12,
            "arr_delta_24h": float(index * 12),
            "revenue_total": float(index * 100),
            "revenue_per_day": float(index * 10),
            "installs_total": 1000 * index,
            "installs_delta_24h": 100 * index,
            "conv_rate": conv_to / conv_from * 100,
            "conv_from": conv_from,
            "conv_to": conv_to,
            "issues": (),
            "is_visible": True,
        })
    return rows


def build_with_rows(
    rows: list[dict],
    portfolio_issues: tuple[IntegrityIssue, ...] = (),
):
    from report_builder import build_report

    snapshot = DailyMetricsSnapshot(
        rows=tuple(rows),
        portfolio_issues=portfolio_issues,
    )
    with patch("report_builder.fetch_daily_snapshot", return_value=snapshot):
        return build_report(date(2026, 8, 6))


class TestReportBuilder(unittest.TestCase):
    def test_complete_report_has_canonical_totals_and_passed_marker(self):
        result = build_with_rows(valid_rows())

        self.assertIn("<b>Unfollowers: Follow &amp; Unfollow</b>", result.text)
        self.assertIn("<b>Granny Photos</b>", result.text)
        self.assertIn("<b>Otty: Couples&amp;Relationships</b>", result.text)
        self.assertIn("Total MRR (на дату): $600 (+$6)", result.text)
        self.assertIn("Total ARR (на дату): $7,200 (+$72)", result.text)
        self.assertIn("Total Revenue (месяц): $600 (+$60)", result.text)
        self.assertIn("Total Downloads (за сутки): (+600)", result.text)
        self.assertIn("Total Conv. (месяц): 1.00%", result.text)
        self.assertIn("✅ Проверка данных: пройдена", result.text)
        self.assertEqual(result.integrity_problem_count, 0)

    def test_partial_report_shows_problem_count_and_na(self):
        rows = valid_rows()
        rows[2]["revenue_total"] = None
        rows[2]["issues"] = (IntegrityIssue(
            code="revenue.invalid",
            message="Revenue response is invalid",
            app_name=CANONICAL_APP_NAMES[2],
            metric="revenue_total",
        ),)

        result = build_with_rows(rows)

        self.assertIn("Revenue (месяц): $N/A (+$30)", result.text)
        self.assertIn("Total Revenue (месяц): $N/A (+$60)", result.text)
        self.assertIn("⚠️ Проверка данных: обнаружено 1 проблем", result.text)
        self.assertIn("Total MRR (на дату): $600", result.text)
        self.assertEqual(result.integrity_problem_count, 1)

    def test_missing_mrr_value_quarantines_only_current_total(self):
        rows = valid_rows()
        rows[2]["mrr_total"] = None

        text = build_with_rows(rows).text

        self.assertIn("MRR (на дату): $N/A (+$3)", text)
        self.assertIn("Total MRR (на дату): $N/A (+$6)", text)
        self.assertIn("Total Revenue (месяц): $600", text)

    def test_missing_mrr_delta_preserves_current_value(self):
        rows = valid_rows()
        rows[2]["mrr_delta_24h"] = None

        text = build_with_rows(rows).text

        self.assertIn("MRR (на дату): $300 (⚠️ N/A)", text)
        self.assertIn("Total MRR (на дату): $600 (⚠️ N/A)", text)

    def test_missing_conversion_counts_make_total_conversion_na(self):
        rows = valid_rows()
        rows[2].update(conv_rate=None, conv_from=None, conv_to=None)

        self.assertIn("Total Conv. (месяц): N/A", build_with_rows(rows).text)

    def test_zero_conversion_counts_render_zero(self):
        rows = valid_rows()
        for row in rows:
            row.update(conv_rate=0.0, conv_from=0, conv_to=0)

        self.assertIn("Total Conv. (месяц): 0.00%", build_with_rows(rows).text)

    def test_total_conversion_uses_raw_counts_not_displayed_rates(self):
        rows = valid_rows()
        rows[0]["conv_rate"] = 99.99
        rows[1]["conv_rate"] = 0.01

        self.assertIn("Total Conv. (месяц): 1.00%", build_with_rows(rows).text)

    def test_portfolio_only_issue_preserves_values_but_warns(self):
        issue = IntegrityIssue(code="config.extra_slot", message="APP4 ignored")

        result = build_with_rows(valid_rows(), portfolio_issues=(issue,))

        self.assertIn("Total MRR (на дату): $600", result.text)
        self.assertIn("⚠️ Проверка данных: обнаружено 1 проблем", result.text)
        self.assertIn("APP4 ignored", result.text)

    def test_issue_details_are_html_escaped(self):
        rows = valid_rows()
        rows[0]["issues"] = (IntegrityIssue(
            code="fetch.failed",
            message="Revenue <invalid> & unavailable",
            app_name=CANONICAL_APP_NAMES[0],
            metric="revenue_total",
        ),)

        text = build_with_rows(rows).text

        self.assertIn("Revenue &lt;invalid&gt; &amp; unavailable", text)
        self.assertNotIn("Revenue <invalid>", text)

    def test_report_uses_provided_date_in_header(self):
        result = build_with_rows(valid_rows())
        self.assertIn("📊 Отчёт на 06.08.2026", result.text)

    def test_audit_records_statuses_without_metric_values(self):
        with self.assertLogs("daily_metric_integrity", level="INFO") as captured:
            build_with_rows(valid_rows())

        output = "\n".join(captured.output)
        self.assertIn("app=Granny Photos metric=mrr_total status=valid", output)
        self.assertIn("total_metric=conversion status=valid", output)
        self.assertNotIn("metric=mrr_total value=", output)


if __name__ == "__main__":
    unittest.main()
