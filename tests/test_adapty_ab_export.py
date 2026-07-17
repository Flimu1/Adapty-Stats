"""Contract tests for strict experiment-scoped Adapty Export metrics."""
from datetime import date
import math
import traceback
import unittest
from unittest.mock import MagicMock

import requests


def response(payload, status=200):
    result = MagicMock()
    result.status_code = status
    result.json.return_value = payload
    return result


def valid_payloads():
    return [
        {"data": {"revenue": {"value": 86.0}}},
        {"data": {"common": {"value_from": 570, "value_to": 8}}},
        {"data": {"common": {"value": 1}}},
    ]


class TestAdaptyAbExportClient(unittest.TestCase):
    def test_rejects_huge_integers_as_invalid_metrics(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        payloads = valid_payloads()
        payloads[0]["data"]["revenue"]["value"] = 10**10000
        session = MagicMock()
        session.post.side_effect = [response(payload) for payload in payloads]
        client = AdaptyAbExportClient("secret-test", session=session, request_interval=0)

        with self.assertRaises(AdaptyAbExportError):
            client.fetch_variant(
                label="A",
                paywall_id="old-paywall",
                test_id="test-123",
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 17),
            )

    def test_rejects_non_finite_revenue(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        for value in (math.nan, math.inf):
            with self.subTest(value=value):
                payloads = valid_payloads()
                payloads[0]["data"]["revenue"]["value"] = value
                session = MagicMock()
                session.post.side_effect = [response(payload) for payload in payloads]
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError):
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

    def test_configures_post_retries_for_rate_limits_and_server_errors(self):
        from adapty_ab_export import AdaptyAbExportClient

        client = AdaptyAbExportClient("secret-test")
        retry = client._session.get_adapter("https://").max_retries

        self.assertEqual(retry.total, 3)
        self.assertSetEqual(set(retry.status_forcelist), {429, 500, 502, 503, 504})
        self.assertSetEqual(set(retry.allowed_methods), {"POST"})
        self.assertTrue(retry.respect_retry_after_header)
        self.assertGreaterEqual(retry.backoff_factor, 0.55)

        no_retry_after = MagicMock(status=429, headers={})
        no_retry_after.get_redirect_location.return_value = None
        after_first_failure = retry.increment(method="POST", response=no_retry_after)
        self.assertGreaterEqual(after_first_failure.get_backoff_time(), 0.55)
        after_second_failure = after_first_failure.increment(
            method="POST", response=no_retry_after
        )
        self.assertGreaterEqual(
            after_second_failure.get_backoff_time(),
            after_first_failure.get_backoff_time(),
        )

    def test_rejects_rate_limit_and_server_errors_after_retries(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                session = MagicMock()
                session.post.return_value = response({}, status=status)
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaisesRegex(AdaptyAbExportError, "temporarily unavailable"):
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

    def test_rejects_transport_failures_without_leaking_sensitive_content(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("secret-test response-body")
        client = AdaptyAbExportClient(
            "secret-test",
            base_url="https://export.example/",
            analytics_path="custom/analytics/",
            timezone="America/New_York",
            session=session,
            request_interval=0,
        )

        with self.assertRaises(AdaptyAbExportError) as captured:
            client.fetch_variant(
                label="A",
                paywall_id="old-paywall",
                test_id="test-123",
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 17),
            )

        self.assertIn("request failed", str(captured.exception))
        self.assertNotIn("secret-test", str(captured.exception))
        self.assertNotIn("response-body", str(captured.exception))
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn(
            "secret-test response-body",
            "".join(traceback.format_exception(captured.exception)),
        )

    def test_zero_views_with_no_purchases_has_zero_conversion_rate(self):
        from adapty_ab_export import AdaptyAbExportClient

        payloads = valid_payloads()
        payloads[0]["data"]["revenue"]["value"] = 0
        payloads[1]["data"]["common"]["value_from"] = 0
        payloads[1]["data"]["common"]["value_to"] = 0
        payloads[2]["data"]["common"]["value"] = 0
        session = MagicMock()
        session.post.side_effect = [response(payload) for payload in payloads]
        client = AdaptyAbExportClient("secret-test", session=session, request_interval=0)

        result = client.fetch_variant(
            label="A",
            paywall_id="old-paywall",
            test_id="test-123",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 17),
        )

        self.assertEqual(result.unique_views, 0)
        self.assertEqual(result.purchases, 0)
        self.assertEqual(result.conversion_rate, 0.0)

    def test_rejects_purchases_when_there_are_no_unique_views(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        payloads = valid_payloads()
        payloads[0]["data"]["revenue"]["value"] = 9.57
        payloads[1]["data"]["common"]["value_from"] = 0
        payloads[1]["data"]["common"]["value_to"] = 1
        payloads[2]["data"]["common"]["value"] = 0
        session = MagicMock()
        session.post.side_effect = [response(payload) for payload in payloads]
        client = AdaptyAbExportClient("secret-test", session=session, request_interval=0)

        with self.assertRaises(AdaptyAbExportError):
            client.fetch_variant(
                label="A",
                paywall_id="old-paywall",
                test_id="test-123",
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 17),
            )

    def test_rejects_fractional_counts(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        count_metrics = (
            (1, ("data", "common", "value_from")),
            (1, ("data", "common", "value_to")),
            (2, ("data", "common", "value")),
        )
        for response_index, path in count_metrics:
            with self.subTest(path=path):
                payloads = valid_payloads()
                current = payloads[response_index]
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = 1.5
                session = MagicMock()
                session.post.side_effect = [response(payload) for payload in payloads]
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError):
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

    def test_rejects_negative_metrics(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        negative_metrics = (
            (0, ("data", "revenue", "value")),
            (1, ("data", "common", "value_from")),
            (1, ("data", "common", "value_to")),
            (2, ("data", "common", "value")),
        )
        for response_index, path in negative_metrics:
            with self.subTest(path=path):
                payloads = valid_payloads()
                current = payloads[response_index]
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = -1
                session = MagicMock()
                session.post.side_effect = [response(payload) for payload in payloads]
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError):
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

    def test_rejects_boolean_and_non_numeric_metrics(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        invalid_metrics = (
            (0, ("data", "revenue", "value"), True),
            (0, ("data", "revenue", "value"), "86.0"),
            (1, ("data", "common", "value_from"), True),
            (1, ("data", "common", "value_to"), "8"),
            (2, ("data", "common", "value"), True),
            (2, ("data", "common", "value"), "1"),
        )
        for response_index, path, value in invalid_metrics:
            with self.subTest(path=path, value=value):
                payloads = valid_payloads()
                current = payloads[response_index]
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = value
                session = MagicMock()
                session.post.side_effect = [response(payload) for payload in payloads]
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError) as captured:
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

                self.assertNotIn("secret-test", str(captured.exception))

    def test_rejects_missing_nested_metric_fields(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        missing_paths = (
            (0, ("data", "revenue", "value")),
            (1, ("data", "common", "value_from")),
            (1, ("data", "common", "value_to")),
            (2, ("data", "common", "value")),
        )
        for response_index, path in missing_paths:
            with self.subTest(path=path):
                payloads = valid_payloads()
                current = payloads[response_index]
                for key in path[:-1]:
                    current = current[key]
                del current[path[-1]]
                session = MagicMock()
                session.post.side_effect = [response(payload) for payload in payloads]
                client = AdaptyAbExportClient(
                    "secret-test", session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError) as captured:
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

                self.assertNotIn("secret-test", str(captured.exception))

    def test_rejects_invalid_json_without_leaking_sensitive_content(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        api_response = response({})
        api_response.text = "response-body secret-test"
        api_response.json.side_effect = ValueError("invalid json")
        session = MagicMock()
        session.post.return_value = api_response
        client = AdaptyAbExportClient("secret-test", session=session, request_interval=0)

        with self.assertRaises(AdaptyAbExportError) as captured:
            client.fetch_variant(
                label="A",
                paywall_id="old-paywall",
                test_id="test-123",
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 17),
            )

        self.assertIn("invalid JSON", str(captured.exception))
        self.assertNotIn("response-body", str(captured.exception))
        self.assertNotIn("secret-test", str(captured.exception))
        self.assertIsNone(captured.exception.__cause__)
        self.assertNotIn(
            "invalid json",
            "".join(traceback.format_exception(captured.exception)),
        )

    def test_rejects_unauthorized_responses_without_leaking_sensitive_content(self):
        from adapty_ab_export import AdaptyAbExportClient, AdaptyAbExportError

        for status in (401, 403):
            with self.subTest(status=status):
                api_key = "secret-test"
                api_response = response({}, status=status)
                api_response.text = "response-body secret-test"
                session = MagicMock()
                session.post.return_value = api_response
                client = AdaptyAbExportClient(
                    api_key, session=session, request_interval=0
                )

                with self.assertRaises(AdaptyAbExportError) as captured:
                    client.fetch_variant(
                        label="A",
                        paywall_id="old-paywall",
                        test_id="test-123",
                        start_date=date(2026, 7, 10),
                        end_date=date(2026, 7, 17),
                    )

                self.assertIn("authentication", str(captured.exception))
                self.assertNotIn("response-body", str(captured.exception))
                self.assertNotIn(api_key, str(captured.exception))

    def test_fetch_variant_scopes_every_request_and_derives_dashboard_aligned_metrics(self):
        from adapty_ab_export import AdaptyAbExportClient

        session = MagicMock()
        session.post.side_effect = [
            response({"data": {"revenue": {"value": 86.11157593263285}}}),
            response({"data": {"common": {"value_from": 570, "value_to": 8}}}),
            response({"data": {"common": {"value": 1}}}),
        ]
        client = AdaptyAbExportClient(
            "secret-test",
            base_url="https://export.example/",
            analytics_path="custom/analytics/",
            timezone="America/New_York",
            session=session,
            request_interval=0,
        )

        result = client.fetch_variant(
            label="A",
            paywall_id="old-paywall",
            test_id="test-123",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 17),
        )

        self.assertEqual(result.revenue, 86.11157593263285)
        self.assertEqual(result.unique_views, 570)
        self.assertEqual(result.purchases, 9)
        self.assertEqual(round(result.arpas, 2), 9.57)
        self.assertEqual(
            [call.kwargs["json"]["chart_id"] for call in session.post.call_args_list],
            ["revenue", "paywall_view_paid", "refund_events"],
        )
        for call in session.post.call_args_list:
            self.assertEqual(call.args[0], "https://export.example/custom/analytics/")
            self.assertEqual(
                call.kwargs["json"]["filters"],
                {
                    "date": ["2026-07-10", "2026-07-17"],
                    "paywall_id": ["old-paywall"],
                    "placement_audience_version_id": ["test-123"],
                },
            )
            self.assertEqual(call.kwargs["json"]["period_unit"], "day")
            self.assertEqual(call.kwargs["json"]["date_type"], "purchase_date")
            self.assertEqual(call.kwargs["json"]["format"], "json")
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Api-Key secret-test")
            self.assertEqual(call.kwargs["headers"]["Adapty-Tz"], "America/New_York")


if __name__ == "__main__":
    unittest.main()
