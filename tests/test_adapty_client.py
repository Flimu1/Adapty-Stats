"""Regression tests for Adapty daily metric collection."""

import unittest


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


if __name__ == "__main__":
    unittest.main()
