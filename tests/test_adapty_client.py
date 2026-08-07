"""Regression tests for Adapty daily metric collection."""

from datetime import date, datetime
import math
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch


MRR_RESPONSE = {
    "data": {
        "revenue": {
            "value": 1272.866100428855,
            "data": [
                {
                    "values": [
                        {"x": "2026-08-05T00:00:00.000000+0300", "y": 1380.73},
                        {
                            "x": "2026-08-06T00:00:00.000000+0300",
                            "y": 1272.866100428855,
                        },
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
        self.assertEqual(metric.daily_dates, ("2026-08-05", "2026-08-06"))

    def test_parses_installs_summary_and_daily_values(self):
        from adapty_client import _parse_chart_metric

        metric = _parse_chart_metric(INSTALLS_RESPONSE, "installs")

        self.assertIsNotNone(metric)
        self.assertEqual(metric.value, 1793.0)
        self.assertEqual(metric.daily_values, (300.0, 321.0))
        self.assertEqual(metric.daily_dates, ("2026-08-01", "2026-08-06"))

    def test_does_not_fall_back_to_proceeds_for_gross_revenue_charts(self):
        from adapty_client import _parse_chart_metric

        payload = {"data": {"proceeds": {"value": 100.0}}}

        self.assertIsNone(_parse_chart_metric(payload, "mrr"))
        self.assertIsNone(_parse_chart_metric(payload, "arr"))
        self.assertIsNone(_parse_chart_metric(payload, "revenue"))

    def test_rejects_boolean_non_finite_and_fractional_install_values(self):
        from adapty_client import _parse_chart_metric

        boolean_value = {"data": {"common": {"value": True, "data": []}}}
        non_finite = {
            "data": {"revenue": {"value": math.inf, "data": []}}
        }
        fractional_installs = {
            "data": {"common": {"value": 3.5, "data": []}}
        }

        self.assertIsNone(_parse_chart_metric(boolean_value, "installs"))
        self.assertIsNone(_parse_chart_metric(non_finite, "mrr"))
        self.assertIsNone(_parse_chart_metric(fractional_installs, "installs"))


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

    def test_rejects_boolean_fractional_and_non_finite_conversion_numbers(self):
        from adapty_client import _parse_conversion_metric

        boolean_count = {**CONVERSION_RESPONSE, "value_from": True}
        fractional_count = {**CONVERSION_RESPONSE, "value_from": 1793.5}
        non_finite_rate = {**CONVERSION_RESPONSE, "value": math.nan}

        self.assertIsNone(_parse_conversion_metric(boolean_count))
        self.assertIsNone(_parse_conversion_metric(fractional_count))
        self.assertIsNone(_parse_conversion_metric(non_finite_rate))

    def test_rejects_unexpected_conversion_metric(self):
        from adapty_client import _parse_conversion_metric

        payload = {**CONVERSION_RESPONSE, "metric_name": "trial_paid"}

        self.assertIsNone(_parse_conversion_metric(payload))


class TestAppSnapshot(unittest.TestCase):
    @patch("adapty_client._pace_request")
    @patch("adapty_client._fetch_conversion")
    @patch("adapty_client._fetch_chart")
    def test_builds_all_fields_from_exactly_five_responses(
        self, mock_fetch_chart, mock_fetch_conversion, mock_pace_request
    ):
        from adapty_client import (
            ChartMetric,
            ConversionMetric,
            _fetch_app_snapshot,
        )

        chart_results = {
            "mrr": ChartMetric(
                1272.87,
                (1380.73, 1272.87),
                ("2026-08-05", "2026-08-06"),
            ),
            "arr": ChartMetric(
                15274.39,
                (16568.72, 15274.39),
                ("2026-08-05", "2026-08-06"),
            ),
            "revenue": ChartMetric(
                262.99,
                (40.0, 30.0, 46.59, 32.65, 11.90),
                (
                    "2026-08-02",
                    "2026-08-03",
                    "2026-08-04",
                    "2026-08-05",
                    "2026-08-06",
                ),
            ),
            "installs": ChartMetric(
                1793.0,
                (300.0, 301.0, 283.0, 321.0),
                ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"),
            ),
        }
        mock_fetch_chart.side_effect = (
            lambda *_args, **_kwargs: chart_results[_args[4]]
        )
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
        session = mock_fetch_chart.call_args_list[0].kwargs["session"]
        self.assertEqual(
            mock_fetch_chart.call_args_list,
            [
                call(*common, "mrr", previous_date, report_date, session=session),
                call(*common, "arr", previous_date, report_date, session=session),
                call(*common, "revenue", month_start, report_date, session=session),
                call(*common, "installs", month_start, report_date, session=session),
            ],
        )
        mock_fetch_conversion.assert_called_once_with(
            "sanitized-key",
            "https://api-admin.adapty.io",
            "api/v1/client-api/metrics/funnel/",
            "Europe/Minsk",
            month_start,
            report_date,
            session=session,
        )
        self.assertEqual(mock_pace_request.call_count, 5)

    @patch("adapty_client._pace_request")
    @patch("adapty_client._fetch_conversion", return_value=None)
    @patch("adapty_client._fetch_chart")
    def test_missing_series_values_remain_missing_but_zero_is_valid(
        self, mock_fetch_chart, _mock_fetch_conversion, _mock_pace_request
    ):
        from adapty_client import ChartMetric, _fetch_app_snapshot

        chart_results = {
            "mrr": ChartMetric(0.0, (0.0,), ("2026-08-06",)),
            "arr": ChartMetric(0.0, (), ()),
            "revenue": ChartMetric(0.0, (), ()),
            "installs": ChartMetric(0.0, (0.0,), ("2026-08-06",)),
        }
        mock_fetch_chart.side_effect = (
            lambda *_args, **_kwargs: chart_results[_args[4]]
        )

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

    @patch("adapty_client._pace_request")
    @patch("adapty_client._fetch_conversion", return_value=None)
    @patch("adapty_client._fetch_chart")
    def test_rejects_stale_final_daily_points(
        self, mock_fetch_chart, _mock_fetch_conversion, _mock_pace_request
    ):
        from adapty_client import ChartMetric, _fetch_app_snapshot

        stale = ChartMetric(100.0, (90.0, 100.0), ("2026-08-04", "2026-08-05"))
        mock_fetch_chart.return_value = stale

        result = _fetch_app_snapshot(
            app_index=0,
            app_key="sanitized-key",
            app_name="Unfollowers: Follow & Unfollow",
            is_visible=True,
            base_url="https://api-admin.adapty.io",
            analytics_path="analytics/",
            conversion_path="conversion/",
            timezone="Europe/Minsk",
            month_start=datetime(2026, 8, 1),
            previous_date=datetime(2026, 8, 5),
            report_date=datetime(2026, 8, 6),
        )

        self.assertIsNone(result["mrr_total"])
        self.assertIsNone(result["mrr_delta_24h"])
        self.assertIsNone(result["arr_total"])
        self.assertIsNone(result["arr_delta_24h"])
        self.assertIsNone(result["revenue_per_day"])
        self.assertIsNone(result["installs_delta_24h"])


class TestRequestReliability(unittest.TestCase):
    def test_session_retries_rate_limits_and_server_errors(self):
        from adapty_client import _get_session

        retries = _get_session().get_adapter("https://").max_retries

        self.assertIn(429, retries.status_forcelist)
        self.assertTrue(retries.respect_retry_after_header)

    @patch("adapty_client.time.sleep")
    @patch("adapty_client.time.monotonic", side_effect=[10.1, 10.5])
    def test_pacer_limits_request_starts_to_two_per_second(
        self, _mock_monotonic, mock_sleep
    ):
        from adapty_client import _pace_request

        started_at = _pace_request(10.0)

        self.assertEqual(mock_sleep.call_count, 1)
        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.4)
        self.assertEqual(started_at, 10.5)


class TestFetchAllMetrics(unittest.TestCase):
    @patch("adapty_client._fetch_app_snapshot")
    @patch("adapty_client.get_adapty_timezone", return_value="Europe/Minsk")
    @patch(
        "adapty_client.get_adapty_conversion_path", return_value="conversion/"
    )
    @patch("adapty_client.get_adapty_analytics_path", return_value="analytics/")
    @patch(
        "adapty_client.get_adapty_base_url",
        return_value="https://api-admin.adapty.io",
    )
    @patch("adapty_client.get_adapty_apps")
    def test_preserves_app_order_and_returns_complete_missing_row_on_failure(
        self,
        mock_get_apps,
        _mock_base_url,
        _mock_analytics_path,
        _mock_conversion_path,
        _mock_timezone,
        mock_snapshot,
    ):
        from adapty_client import fetch_all_metrics

        mock_get_apps.return_value = [
            SimpleNamespace(api_key="key-1", name="First", is_visible=True),
            SimpleNamespace(api_key="key-2", name="Second", is_visible=True),
            SimpleNamespace(api_key="key-3", name="Third", is_visible=True),
        ]

        def snapshot_result(**kwargs):
            if kwargs["app_index"] == 1:
                raise RuntimeError("sanitized failure")
            return {
                "index": kwargs["app_index"],
                "name": kwargs["app_name"],
                "is_visible": kwargs["is_visible"],
            }

        mock_snapshot.side_effect = snapshot_result

        rows = fetch_all_metrics(report_date=date(2026, 8, 6))

        self.assertEqual([row["name"] for row in rows], ["First", "Second", "Third"])
        failed = rows[1]
        self.assertIsNone(failed["mrr_total"])
        self.assertIsNone(failed["arr_total"])
        self.assertIsNone(failed["revenue_total"])
        self.assertIsNone(failed["installs_total"])
        self.assertIsNone(failed["conv_rate"])
        self.assertIsNone(failed["conv_from"])
        self.assertIsNone(failed["conv_to"])


if __name__ == "__main__":
    unittest.main()
