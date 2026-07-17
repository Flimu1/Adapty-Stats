"""Contract tests for experiment-scoped Adapty dashboard metrics."""
import unittest
from unittest.mock import MagicMock


TEST_ID = "ab-test-123"
APP_ID = "app-456"
NEW_PAYWALL_ID = "d6765d7f-eb06-42db-8d0d-ee21e2b41fe8"
OLD_PAYWALL_ID = "d6d24875-e330-4ad9-8ee0-841d3452a911"


def _metadata_payload():
    return {
        "data": {
            "ab_test_id": TEST_ID,
            "title": "Test paywall prices. 4.99/29.99 vs 5.99/39.99",
            "paywalls": [
                {
                    "paywall": {
                        "paywall_id": OLD_PAYWALL_ID,
                        "title": "New Paywall Old Prices ",
                    },
                    "weight": 50,
                },
                {
                    "paywall": {
                        "paywall_id": NEW_PAYWALL_ID,
                        "title": "New Paywall New Prices",
                    },
                    "weight": 50,
                },
            ],
        }
    }


def _metrics_payload():
    return {
        "data": [
            {
                "ab_test_id": TEST_ID,
                "items": [
                    {
                        "paywall_id": NEW_PAYWALL_ID,
                        "revenue": 163.2467,
                        "average_per_1000": 291.0,
                        "proceeds": 139.0,
                        "net_revenue": 124.0,
                        "probability": 87.82,
                        "arpas": 8.86,
                        "views": 446,
                        "purchases": 12,
                        "conversion_rate_purchases": 2.69,
                        "items": [],
                    },
                    {
                        "paywall_id": OLD_PAYWALL_ID,
                        "revenue": 86.0,
                        "average_per_1000": 155.0,
                        "proceeds": 73.0,
                        "net_revenue": 69.0,
                        "probability": 12.18,
                        "arpas": 5.95,
                        "views": 527,
                        "purchases": 8,
                        "conversion_rate_purchases": 1.52,
                        "items": [],
                    },
                ],
            }
        ]
    }


def _response(payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    return response


class TestAdaptyAbDashboardClient(unittest.TestCase):
    def _client(self, responses, token="dashboard-secret"):
        from adapty_ab_dashboard import AdaptyAbDashboardClient

        session = MagicMock()
        session.get.side_effect = responses
        client = AdaptyAbDashboardClient(
            app_id=APP_ID,
            token=token,
            session=session,
        )
        return client, session

    def test_normalizes_dashboard_authorization(self):
        from adapty_ab_dashboard import normalize_dashboard_authorization

        self.assertEqual(
            normalize_dashboard_authorization("dashboard-secret"),
            "Bearer dashboard-secret",
        )
        self.assertEqual(
            normalize_dashboard_authorization("Bearer dashboard-secret"),
            "Bearer dashboard-secret",
        )

    def test_fetches_exact_experiment_endpoints_and_parses_variants(self):
        client, session = self._client(
            [_response(_metadata_payload()), _response(_metrics_payload())]
        )

        result = client.fetch_metrics(
            test_id=TEST_ID,
            expected_test_name="Test paywall prices. 4.99/29.99 vs 5.99/39.99",
            expected_variants={
                "A": (OLD_PAYWALL_ID, "New Paywall Old Prices"),
                "B": (NEW_PAYWALL_ID, "New Paywall New Prices"),
            },
        )

        self.assertEqual(result.test_id, TEST_ID)
        self.assertEqual([item.label for item in result.variants], ["A", "B"])
        self.assertEqual(result.variants[0].paywall_id, OLD_PAYWALL_ID)
        self.assertAlmostEqual(result.variants[0].revenue, 86.0)
        self.assertEqual(result.variants[0].views, 527)
        self.assertEqual(result.variants[0].purchases, 8)
        self.assertAlmostEqual(result.variants[1].revenue, 163.2467)

        metadata_call, metrics_call = session.get.call_args_list
        self.assertEqual(
            metadata_call.args[0],
            f"https://api-admin.adapty.io/api/v1/portal/{APP_ID}/in-apps/ab-tests/{TEST_ID}/",
        )
        self.assertEqual(
            metrics_call.args[0],
            f"https://api-admin.adapty.io/api/v1/portal/{APP_ID}/analytics/ab-tests/metrics/",
        )
        self.assertEqual(metrics_call.kwargs["params"], {"filter[ab_test_id]": TEST_ID})
        self.assertEqual(
            metadata_call.kwargs["headers"]["Authorization"],
            "Bearer dashboard-secret",
        )

    def test_fails_closed_on_unauthorized_response(self):
        from adapty_ab_dashboard import AdaptyDashboardError

        client, _session = self._client([_response({}, status=401)])

        with self.assertRaisesRegex(AdaptyDashboardError, "authentication"):
            client.fetch_metrics(TEST_ID, "Price test", {})

    def test_fails_closed_when_configured_mapping_is_reversed(self):
        from adapty_ab_dashboard import AdaptyDashboardError

        client, _session = self._client(
            [_response(_metadata_payload()), _response(_metrics_payload())]
        )

        with self.assertRaisesRegex(AdaptyDashboardError, "variant A"):
            client.fetch_metrics(
                TEST_ID,
                "Test paywall prices. 4.99/29.99 vs 5.99/39.99",
                {
                    "A": (NEW_PAYWALL_ID, "New Paywall New Prices"),
                    "B": (OLD_PAYWALL_ID, "New Paywall Old Prices"),
                },
            )

    def test_fails_closed_when_required_metric_is_missing(self):
        from adapty_ab_dashboard import AdaptyDashboardError

        payload = _metrics_payload()
        del payload["data"][0]["items"][0]["views"]
        client, _session = self._client(
            [_response(_metadata_payload()), _response(payload)]
        )

        with self.assertRaisesRegex(AdaptyDashboardError, "views"):
            client.fetch_metrics(
                TEST_ID,
                "Test paywall prices. 4.99/29.99 vs 5.99/39.99",
                {
                    "A": (OLD_PAYWALL_ID, "New Paywall Old Prices"),
                    "B": (NEW_PAYWALL_ID, "New Paywall New Prices"),
                },
            )

    def test_fails_closed_when_displayed_dashboard_metric_is_missing(self):
        from adapty_ab_dashboard import AdaptyDashboardError

        payload = _metrics_payload()
        del payload["data"][0]["items"][0]["proceeds"]
        client, _session = self._client(
            [_response(_metadata_payload()), _response(payload)]
        )

        with self.assertRaisesRegex(AdaptyDashboardError, "proceeds"):
            client.fetch_metrics(
                TEST_ID,
                "Test paywall prices. 4.99/29.99 vs 5.99/39.99",
                {
                    "A": (OLD_PAYWALL_ID, "New Paywall Old Prices"),
                    "B": (NEW_PAYWALL_ID, "New Paywall New Prices"),
                },
            )

    def test_fails_closed_on_invalid_json(self):
        from adapty_ab_dashboard import AdaptyDashboardError

        response = _response({})
        response.json.side_effect = ValueError("invalid json")
        client, _session = self._client([response])

        with self.assertRaisesRegex(AdaptyDashboardError, "invalid JSON"):
            client.fetch_metrics(TEST_ID, "Price test", {})


if __name__ == "__main__":
    unittest.main()
