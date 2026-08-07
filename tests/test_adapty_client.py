"""Regression tests for Adapty daily metric collection."""

from datetime import datetime
import unittest
from unittest.mock import call, patch


MRR_RESPONSE = {
    "data": {
        "revenue": {
            "value": 1272.866100428855,
            "data": [
                {
                    "values": [
                        {"x": "2026-08-05", "y": 1380.73},
                        {"x": "2026-08-06", "y": 1272.866100428855},
                    ]
                }
            ],
        },
        "proceeds": {
            "value": 890.0,
            "data": [{"values": [{"x": "2026-08-06", "y": 890.0}]}],
        },
    }
}

INSTALLS_RESPONSE = {
    "data": {
        "common": {
            "value": 1793,
            "data": [
                {
                    "values": [
                        {"x": "2026-08-01", "y": 300},
                        {"x": "2026-08-06", "y": 321},
                    ]
                }
            ],
        }
    }
}

CONVERSION_RESPONSE = {
    "value": 0.8365867261572784,
    "value_from": 1793,
    "value_to": 15,
    "metric_name": "install_paid",
    "data": [],
}


class TestChartMetricParsing(unittest.TestCase):
    def test_parses_gross_mrr_summary_and_daily_values(self):
        from adapty_client import _parse_chart_metric

        metric = _parse_chart_metric(MRR_RESPONSE, "mrr")

        self.assertIsNotNone(metric)
        self.assertEqual(metric.value, 1272.866100428855)
        self.assertEqual(metric.daily_values, (1380.73, 1272.866100428855))

    def test_parses_installs_summary_and_daily_values(self):
        from adapty_client import _parse_chart_metric

        metric = _parse_chart_metric(INSTALLS_RESPONSE, "installs")

        self.assertIsNotNone(metric)
        self.assertEqual(metric.value, 1793.0)
        self.assertEqual(metric.daily_values, (300.0, 321.0))

    def test_does_not_fall_back_to_proceeds_for_gross_revenue_charts(self):
        from adapty_client import _parse_chart_metric

        payload = {"data": {"proceeds": {"value": 100.0}}}

        self.assertIsNone(_parse_chart_metric(payload, "mrr"))
        self.assertIsNone(_parse_chart_metric(payload, "arr"))
        self.assertIsNone(_parse_chart_metric(payload, "revenue"))


class TestConversionMetricParsing(unittest.TestCase):
    def test_preserves_percentage_and_raw_counts(self):
        from adapty_client import _parse_conversion_metric

        metric = _parse_conversion_metric(CONVERSION_RESPONSE)

        self.assertIsNotNone(metric)
        self.assertEqual(metric.value, 0.8365867261572784)
        self.assertEqual(metric.value_from, 1793)
        self.assertEqual(metric.value_to, 15)

    def test_rejects_missing_or_invalid_raw_counts(self):
        from adapty_client import _parse_conversion_metric

        missing_count = dict(CONVERSION_RESPONSE)
        missing_count.pop("value_from")
        negative_count = {**CONVERSION_RESPONSE, "value_to": -1}
        too_many_paid = {**CONVERSION_RESPONSE, "value_from": 10, "value_to": 11}

        self.assertIsNone(_parse_conversion_metric(missing_count))
        self.assertIsNone(_parse_conversion_metric(negative_count))
        self.assertIsNone(_parse_conversion_metric(too_many_paid))

    def test_rejects_unexpected_conversion_metric(self):
        from adapty_client import _parse_conversion_metric

        payload = {**CONVERSION_RESPONSE, "metric_name": "trial_paid"}

        self.assertIsNone(_parse_conversion_metric(payload))


class TestAppSnapshot(unittest.TestCase):
    @patch("adapty_client._fetch_conversion")
    @patch("adapty_client._fetch_chart")
    def test_builds_all_fields_from_exactly_five_responses(
        self, mock_fetch_chart, mock_fetch_conversion
    ):
        from adapty_client import (
            ChartMetric,
            ConversionMetric,
            _fetch_app_snapshot,
        )

        chart_results = {
            "mrr": ChartMetric(1272.87, (1380.73, 1272.87)),
            "arr": ChartMetric(15274.39, (16568.72, 15274.39)),
            "revenue": ChartMetric(262.99, (40.0, 30.0, 46.59, 32.65, 11.90)),
            "installs": ChartMetric(1793.0, (300.0, 301.0, 283.0, 321.0)),
        }
        mock_fetch_chart.side_effect = lambda *_args: chart_results[_args[4]]
        mock_fetch_conversion.return_value = ConversionMetric(
            0.8365867261572784, 1793, 15
        )
        month_start = datetime(2026, 8, 1)
        previous_date = datetime(2026, 8, 5)
        report_date = datetime(2026, 8, 6)

        result = _fetch_app_snapshot(
            app_index=0,
            app_key="sanitized-key",
            app_name="Unfollowers: Follow & Unfollow",
            is_visible=True,
            base_url="https://api-admin.adapty.io",
            analytics_path="api/v1/client-api/metrics/analytics/",
            conversion_path="api/v1/client-api/metrics/funnel/",
            timezone="Europe/Minsk",
            month_start=month_start,
            previous_date=previous_date,
            report_date=report_date,
        )

        self.assertEqual(result["mrr_total"], 1272.87)
        self.assertAlmostEqual(result["mrr_delta_24h"], -107.86)
        self.assertEqual(result["arr_total"], 15274.39)
        self.assertAlmostEqual(result["arr_delta_24h"], -1294.33)
        self.assertEqual(result["revenue_total"], 262.99)
        self.assertEqual(result["revenue_per_day"], 11.90)
        self.assertEqual(result["installs_total"], 1793)
        self.assertEqual(result["installs_delta_24h"], 321)
        self.assertEqual(result["conv_rate"], 0.8365867261572784)
        self.assertEqual(result["conv_from"], 1793)
        self.assertEqual(result["conv_to"], 15)
        self.assertEqual(result["name"], "Unfollowers: Follow & Unfollow")
        self.assertTrue(result["is_visible"])

        common = (
            "sanitized-key",
            "https://api-admin.adapty.io",
            "api/v1/client-api/metrics/analytics/",
            "Europe/Minsk",
        )
        self.assertEqual(
            mock_fetch_chart.call_args_list,
            [
                call(*common, "mrr", previous_date, report_date),
                call(*common, "arr", previous_date, report_date),
                call(*common, "revenue", month_start, report_date),
                call(*common, "installs", month_start, report_date),
            ],
        )
        mock_fetch_conversion.assert_called_once_with(
            "sanitized-key",
            "https://api-admin.adapty.io",
            "api/v1/client-api/metrics/funnel/",
            "Europe/Minsk",
            month_start,
            report_date,
        )

    @patch("adapty_client._fetch_conversion", return_value=None)
    @patch("adapty_client._fetch_chart")
    def test_missing_series_values_remain_missing_but_zero_is_valid(
        self, mock_fetch_chart, _mock_fetch_conversion
    ):
        from adapty_client import ChartMetric, _fetch_app_snapshot

        chart_results = {
            "mrr": ChartMetric(0.0, (0.0,)),
            "arr": ChartMetric(0.0, ()),
            "revenue": ChartMetric(0.0, ()),
            "installs": ChartMetric(0.0, (0.0,)),
        }
        mock_fetch_chart.side_effect = lambda *_args: chart_results[_args[4]]

        result = _fetch_app_snapshot(
            app_index=1,
            app_key="sanitized-key",
            app_name="Granny Photos",
            is_visible=True,
            base_url="https://api-admin.adapty.io",
            analytics_path="analytics/",
            conversion_path="funnel/",
            timezone="Europe/Minsk",
            month_start=datetime(2026, 8, 1),
            previous_date=datetime(2026, 8, 5),
            report_date=datetime(2026, 8, 6),
        )

        self.assertEqual(result["mrr_total"], 0.0)
        self.assertIsNone(result["mrr_delta_24h"])
        self.assertIsNone(result["arr_total"])
        self.assertIsNone(result["arr_delta_24h"])
        self.assertEqual(result["revenue_total"], 0.0)
        self.assertIsNone(result["revenue_per_day"])
        self.assertEqual(result["installs_total"], 0)
        self.assertEqual(result["installs_delta_24h"], 0)
        self.assertIsNone(result["conv_rate"])
        self.assertIsNone(result["conv_from"])
        self.assertIsNone(result["conv_to"])


if __name__ == "__main__":
    unittest.main()
