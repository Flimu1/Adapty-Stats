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
    report_date: date = date(2026, 8, 6),
):
    from report_builder import build_report

    snapshot = DailyMetricsSnapshot(
        rows=tuple(rows),
        portfolio_issues=portfolio_issues,
    )
    with patch("report_builder.fetch_daily_snapshot", return_value=snapshot):
        return build_report(report_date)


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
        self.assertIn("ARR (на дату): $1,200 (+$12)", result.text)
        self.assertIn("Conv. Install→Paid (месяц): 1.00% (1/100)", result.text)
        self.assertIn("Total Conv. (месяц): 1.00% (6/600)", result.text)
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

        self.assertIn("Revenue (месяц): $N/A (⚠️ N/A)", result.text)
        self.assertIn("Total Revenue (месяц): $N/A (⚠️ N/A)", result.text)
        self.assertIn("⚠️ Проверка данных: обнаружено 1 проблем", result.text)
        self.assertIn("Total MRR (на дату): $600", result.text)
        self.assertEqual(result.integrity_problem_count, 1)

    def test_missing_mrr_value_quarantines_only_current_total(self):
        rows = valid_rows()
        rows[2]["mrr_total"] = None

        text = build_with_rows(rows).text

        self.assertIn("MRR (на дату): $N/A (⚠️ N/A)", text)
        self.assertIn("Total MRR (на дату): $N/A (⚠️ N/A)", text)
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

    def test_zero_conversion_denominator_renders_na(self):
        rows = valid_rows()
        for row in rows:
            row.update(conv_rate=0.0, conv_from=0, conv_to=0)

        self.assertIn("Total Conv. (месяц): N/A (0/0)", build_with_rows(rows).text)

    def test_missing_revenue_mtd_never_carries_numeric_daily_value(self):
        rows = valid_rows()
        rows[2]["revenue_total"] = None

        text = build_with_rows(rows).text

        self.assertIn("Revenue (месяц): $N/A (⚠️ N/A)", text)
        self.assertIn("Total Revenue (месяц): $N/A (⚠️ N/A)", text)

    def test_total_conversion_uses_raw_counts_not_displayed_rates(self):
        rows = valid_rows()
        rows[0]["conv_rate"] = 99.99
        rows[1]["conv_rate"] = 0.01

        self.assertIn("Total Conv. (месяц): 1.00% (6/600)", build_with_rows(rows).text)

    def test_money_totals_sum_the_same_cent_values_shown_per_app(self):
        rows = valid_rows()
        for row in rows:
            row.update(
                mrr_total=0.004,
                mrr_delta_24h=0.004,
                arr_total=0.004,
                arr_delta_24h=0.004,
                revenue_total=0.004,
                revenue_per_day=0.004,
            )

        text = build_with_rows(rows).text

        self.assertEqual(text.count("MRR (на дату): $0 (+$0)"), 4)
        self.assertIn("Total ARR (на дату): $0 (+$0)", text)
        self.assertIn("Total Revenue (месяц): $0 (+$0)", text)

    def test_integer_totals_preserve_counts_above_float_precision(self):
        rows = valid_rows()
        denominators = [9_007_199_254_740_993, 9_007_199_254_740_995, 9_007_199_254_740_991]
        download_deltas = [9_007_199_254_740_993, 3, 5]
        for row, denominator, download_delta in zip(
            rows, denominators, download_deltas
        ):
            row.update(
                conv_from=denominator,
                conv_to=1,
                conv_rate=1 / denominator * 100,
                installs_total=denominator,
                installs_delta_24h=download_delta,
            )

        text = build_with_rows(rows).text

        self.assertIn(
            f"Total Conv. (месяц): 0.00% (3/{sum(denominators):,})",
            text,
        )
        self.assertIn(
            f"Total Downloads (за сутки): (+{sum(download_deltas):,})",
            text,
        )

    def test_august_six_backfill_uses_canonical_installs_snapshot(self):
        rows = valid_rows()
        rows[0].update(
            mrr_total=1272.87,
            mrr_delta_24h=-104.63,
            arr_total=15274.44,
            arr_delta_24h=-1255.56,
            revenue_total=262.99,
            revenue_per_day=11.90,
            installs_total=1793,
            installs_delta_24h=321,
        )

        text = build_with_rows(rows).text

        self.assertIn("📊 Отчёт на 06.08.2026", text)
        self.assertIn("Installs (месяц): 1,793 (+321)", text)
        self.assertNotIn("Installs (месяц): 1,784", text)

    def test_august_four_to_six_backfill_snapshots_pass_validation_pipeline(self):
        from daily_metric_integrity import validate_app_metrics

        fixtures = {
            date(2026, 8, 4): (
                ((1183, 306, 11), (3, 2, 0), (612, 115, 0)),
                1798,
                423,
                1178,
            ),
            date(2026, 8, 5): (
                ((1472, 289, 11), (3, 0, 0), (742, 130, 0)),
                2217,
                419,
                1466,
            ),
            date(2026, 8, 6): (
                ((1793, 321, 15), (4, 1, 0), (1021, 279, 0)),
                2818,
                601,
                1784,
            ),
        }

        for report_date, (apps, total_installs, daily_downloads, stale_value) in fixtures.items():
            with self.subTest(report_date=report_date):
                rows = valid_rows()
                for row, (installs, daily, paid) in zip(rows, apps):
                    row.update(
                        installs_total=installs,
                        installs_delta_24h=daily,
                        conv_from=installs,
                        conv_to=paid,
                        conv_rate=paid / installs * 100,
                    )
                validated = [validate_app_metrics(row) for row in rows]

                self.assertTrue(all(not row["issues"] for row in validated))
                text = build_with_rows(validated, report_date=report_date).text
                self.assertIn(f"({sum(app[2] for app in apps)}/{total_installs:,})", text)
                self.assertIn(f"Total Downloads (за сутки): (+{daily_downloads})", text)
                self.assertNotIn(f"Installs (месяц): {stale_value:,}", text)
                self.assertIn("✅ Проверка данных: пройдена", text)

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
