"""
Тест формата отчёта и расчёта Total MRR / Total Downloads.
Запуск из корня: python -m pytest tests/test_report_builder.py -v
или: python tests/test_report_builder.py
"""
from datetime import date
import unittest
from unittest.mock import patch


def _mock_fetch_all_metrics(*_args, **_kwargs):
    """Мок: два приложения с известными суммами для проверки Total."""
    return [
        {
            "index": 0,
            "name": "App One",
            "mrr_total": 1000.5,
            "mrr_delta_24h": 50.25,
            "arr_total": 12006.0,
            "arr_delta_24h": 603.0,
            "revenue_total": 200.0,
            "revenue_per_day": 25.0,
            "installs_total": 5000,
            "installs_delta_24h": 120,
            "conv_rate": 1.2,
            "conv_from": 5000,
            "conv_to": 60,
            "is_visible": True,
        },
        {
            "index": 1,
            "name": "App Two",
            "mrr_total": 2000.0,
            "mrr_delta_24h": -10.5,
            "arr_total": 24000.0,
            "arr_delta_24h": -126.0,
            "revenue_total": 300.0,
            "revenue_per_day": 35.0,
            "installs_total": 3000,
            "installs_delta_24h": 80,
            "conv_rate": 1.0,
            "conv_from": 3000,
            "conv_to": 30,
            "is_visible": True,
        },
    ]


def _mock_fetch_all_metrics_with_anomaly(*_args, **_kwargs):
    """Мок с неконсистентными installs для проверки аномалий."""
    return [
        {
            "index": 0,
            "name": "Broken App",
            "mrr_total": 100.0,
            "mrr_delta_24h": 5.0,
            "arr_total": 1200.0,
            "arr_delta_24h": 60.0,
            "revenue_total": 50.0,
            "revenue_per_day": 5.0,
            "installs_total": 20,
            "installs_delta_24h": 25,
            "conv_rate": 5.0,
            "conv_from": 20,
            "conv_to": 1,
            "is_visible": True,
        }
    ]


def _mock_fetch_with_hidden_app(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    rows.append(
        {
            "index": 2,
            "name": "Hidden Portfolio App",
            "mrr_total": 999999.0,
            "mrr_delta_24h": 888888.0,
            "arr_total": 777777.0,
            "arr_delta_24h": 666666.0,
            "revenue_total": 555555.0,
            "revenue_per_day": 444444.0,
            "installs_total": 333333,
            "installs_delta_24h": 222222,
            "conv_rate": 100.0,
            "conv_from": 111111,
            "conv_to": 111111,
            "is_visible": False,
        }
    )
    return rows


def _mock_fetch_with_missing_revenue(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    rows[1]["revenue_total"] = None
    return rows


def _mock_fetch_with_changed_rounded_rates(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    rows[0]["conv_rate"] = 99.99
    rows[1]["conv_rate"] = 0.01
    return rows


def _mock_fetch_with_missing_conversion_count(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    rows[1]["conv_from"] = None
    return rows


def _mock_fetch_with_multiple_missing_fields(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    rows[0]["arr_total"] = None
    rows[0]["revenue_per_day"] = None
    rows[0]["conv_rate"] = None
    rows[0]["conv_to"] = None
    return rows


def _mock_fetch_with_zero_values(*_args, **_kwargs):
    rows = _mock_fetch_all_metrics()
    numeric_fields = (
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
    for row in rows:
        for field in numeric_fields:
            row[field] = 0
    return rows


def _mock_fetch_august_6_after_backfill(*_args, **_kwargs):
    return [
        {
            "index": 0,
            "name": "Unfollowers: Follow & Unfollow",
            "mrr_total": 1272.866100428855,
            "mrr_delta_24h": -104.63,
            "arr_total": 15274.393205146269,
            "arr_delta_24h": -1255.53,
            "revenue_total": 262.9883818251301,
            "revenue_per_day": 11.90,
            "installs_total": 1793,
            "installs_delta_24h": 321,
            "conv_rate": 0.8365867261572784,
            "conv_from": 1793,
            "conv_to": 15,
            "is_visible": True,
        }
    ]


class TestReportBuilder(unittest.TestCase):
    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_report_contains_total_section(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        self.assertIn("<b>Total</b>", text)
        self.assertIn("Total MRR", text)
        self.assertIn("Total Downloads", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_report_does_not_include_legacy_explainer_text(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        self.assertNotIn("MRR, ARR — на дату", text)
        self.assertNotIn("Revenue, Installs, Conv — за месяц", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_mrr_is_sum_of_current_mrr(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 1000.5 + 2000 = 3000.5 → формат $3,000.50
        self.assertIn("3,000.50", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_mrr_delta_in_parentheses(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 50.25 + (-10.5) = 39.75 → (+$39.75)
        self.assertIn("+$39.75", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_negative_mrr_delta_sign_before_currency(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # Для отрицательной дельты формат должен быть (-$10.50), а не ($-10.50)
        self.assertIn("(-$10.50)", text)
        self.assertNotIn("($-10.50)", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_downloads_is_sum_of_deltas(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 120 + 80 = 200 → (+200)
        self.assertIn("+200", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_app_blocks_present(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        self.assertIn("<b>App One</b>", text)
        self.assertIn("<b>App Two</b>", text)
        self.assertIn("💰 MRR", text)
        self.assertIn("📲 Installs", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_report_uses_provided_report_date_in_header(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 2, 14))
        self.assertIn("📊 Отчёт на 14.02.2026", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics_with_anomaly)
    def test_anomaly_banner_present_when_detected(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 2, 14))
        self.assertIn("Обнаружены аномалии в данных", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_with_hidden_app)
    def test_hidden_rows_are_excluded_from_every_total(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertNotIn("Hidden Portfolio App", text)
        self.assertIn("Total MRR (на дату): $3,000.50 (+$39.75)", text)
        self.assertIn("Total ARR (на дату): $36,006 (+$477)", text)
        self.assertIn("Total Revenue (месяц): $500 (+$60)", text)
        self.assertIn("Total Downloads (за сутки): (+200)", text)
        self.assertIn("Total Conv. (месяц): 1.12%", text)
        self.assertNotIn("999,999", text)
        self.assertNotIn("222,422", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_conversion_uses_summed_raw_counts(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertIn("Total Conv. (месяц): 1.12%", text)

    @patch(
        "report_builder.fetch_all_metrics",
        side_effect=_mock_fetch_with_changed_rounded_rates,
    )
    def test_total_conversion_does_not_use_displayed_app_rates(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertIn("Total Conv. (месяц): 1.12%", text)

    @patch(
        "report_builder.fetch_all_metrics",
        side_effect=_mock_fetch_with_missing_conversion_count,
    )
    def test_missing_conversion_count_makes_total_conversion_na(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertIn("Total Conv. (месяц): N/A", text)

    @patch(
        "report_builder.fetch_all_metrics", side_effect=_mock_fetch_with_missing_revenue
    )
    def test_missing_visible_metric_makes_only_its_total_na(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertIn("Total MRR (на дату): $3,000.50", text)
        self.assertIn("Total Revenue (месяц): $N/A (+$60)", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_with_zero_values)
    def test_zero_is_valid_and_is_not_rendered_as_missing(self, _mock_fetch):
        from report_builder import build_report

        result = build_report(report_date=date(2026, 8, 6))

        self.assertNotIn("Некоторые данные недоступны", result.text)
        self.assertIn("Total MRR (на дату): $0 (+$0)", result.text)
        self.assertIn("Total Revenue (месяц): $0 (+$0)", result.text)
        self.assertIn("Total Downloads (за сутки): (+0)", result.text)
        self.assertIn("Total Conv. (месяц): N/A", result.text)
        self.assertEqual(result.anomalies, [])

    @patch(
        "report_builder.fetch_all_metrics",
        side_effect=_mock_fetch_with_multiple_missing_fields,
    )
    def test_anomalies_name_every_missing_metric_family(self, _mock_fetch):
        from report_builder import build_report

        result = build_report(report_date=date(2026, 8, 6))
        anomaly_text = "\n".join(result.anomalies)

        self.assertIn("App One", anomaly_text)
        self.assertIn("ARR", anomaly_text)
        self.assertIn("Revenue day", anomaly_text)
        self.assertIn("Conversion", anomaly_text)
        self.assertIn("Conversion paid", anomaly_text)

    @patch(
        "report_builder.fetch_all_metrics",
        side_effect=_mock_fetch_with_multiple_missing_fields,
    )
    def test_report_renders_application_and_missing_metric_details(self, _mock_fetch):
        from report_builder import build_report

        result = build_report(report_date=date(2026, 8, 6))

        self.assertIn("• App One: отсутствуют поля", result.text)
        self.assertIn("Revenue day", result.text)
        self.assertIn("Conversion paid", result.text)

    @patch(
        "report_builder.fetch_all_metrics",
        side_effect=_mock_fetch_august_6_after_backfill,
    )
    def test_august_6_snapshot_accepts_late_install_backfill(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text(report_date=date(2026, 8, 6))

        self.assertIn("Installs (месяц): 1,793 (+321)", text)
        self.assertIn("Conv. Install→Paid (месяц): 0.84%", text)
        self.assertIn("Total Downloads (за сутки): (+321)", text)
        self.assertNotIn("1,784", text)


if __name__ == "__main__":
    unittest.main()
