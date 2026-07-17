"""Tests for the validated Adapty A/B Telegram report."""
from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch


def _enabled_config():
    from ab_test_report import AbTestConfig, AbTestVariantConfig

    return AbTestConfig(
        enabled=True,
        app_index=1,
        app_name="Unfollowers: Follow & Unfollow",
        test_name="Test paywall prices. 4.99/29.99 vs 5.99/39.99",
        start_date=date(2026, 7, 10),
        variant_a=AbTestVariantConfig("A", "old-paywall", "New Paywall Old Prices"),
        variant_b=AbTestVariantConfig("B", "new-paywall", "New Paywall New Prices"),
        test_id="test-123",
        dashboard_app_id="app-456",
        dashboard_token="Bearer dashboard-secret",
    )


def _snapshot():
    from ab_test_report import AbTestReportSnapshot, AbTestVariantMetrics

    return AbTestReportSnapshot(
        rows=[
            AbTestVariantMetrics(
                label="A",
                paywall_name="New Paywall Old Prices",
                revenue=86.0,
                paywall_views=527,
                purchases=8,
                arpas=5.95,
                revenue_per_1000=155.0,
                proceeds=73.0,
                net_revenue=69.0,
                probability=12.18,
            ),
            AbTestVariantMetrics(
                label="B",
                paywall_name="New Paywall New Prices",
                revenue=163.2467,
                paywall_views=446,
                purchases=12,
                arpas=8.86,
                revenue_per_1000=291.0,
                proceeds=139.0,
                net_revenue=124.0,
                probability=87.82,
            ),
        ],
        collected_at=datetime(2026, 7, 17, 12, 41, tzinfo=timezone.utc),
    )


class TestAbTestReport(unittest.TestCase):
    @patch("ab_test_report.fetch_ab_test_metrics", side_effect=lambda *_: _snapshot())
    @patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config)
    def test_formats_dashboard_metrics_source_snapshot_and_latency_note(
        self, _mock_config, _mock_fetch
    ):
        from ab_test_report import build_ab_test_report

        text = build_ab_test_report(report_date=date(2026, 7, 17))

        self.assertIn("🧪 A/B Test: Test paywall prices. 4.99/29.99 vs 5.99/39.99", text)
        self.assertIn("📱 App: Unfollowers: Follow &amp; Unfollow", text)
        self.assertIn("🔎 Source: Adapty A/B Test Details", text)
        self.assertIn("🕒 Snapshot: 17.07.2026 15:41 (Europe/Minsk)", text)
        self.assertIn("<b>A / New Paywall Old Prices</b>", text)
        self.assertIn("💵 Revenue: $163.25", text)
        self.assertIn("📊 Revenue per 1K users: $291", text)
        self.assertIn("💰 Proceeds: $139", text)
        self.assertIn("🏦 Net proceeds: $124", text)
        self.assertIn("🎯 P2BB: 87.82%", text)
        self.assertIn("📈 ARPAS: $8.86", text)
        self.assertIn("📲 Paywall views: 446", text)
        self.assertIn("💳 Purchases: 12", text)
        self.assertIn("🔄 CR view→purchase: 2.69%", text)
        self.assertIn("<b>B / New Paywall New Prices</b>", text)
        self.assertIn("🏆 Лидер по revenue: B (+$77.25)", text)
        self.assertIn("Views обновляются Adapty периодически", text)

    def test_variant_metrics_handles_zero_views_without_division_by_zero(self):
        from ab_test_report import AbTestVariantMetrics

        metrics = AbTestVariantMetrics("A", "Paywall", 10.0, 0, 2, 1.0)
        self.assertIsNone(metrics.conversion_rate)

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config")
    def test_returns_none_when_disabled(self, mock_config, mock_fetch):
        from ab_test_report import AbTestConfig, AbTestVariantConfig, build_ab_test_report

        mock_config.return_value = AbTestConfig(
            False,
            1,
            "",
            "",
            date.today(),
            AbTestVariantConfig("", "", ""),
            AbTestVariantConfig("", "", ""),
        )

        self.assertIsNone(build_ab_test_report())
        mock_fetch.assert_not_called()

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config)
    def test_propagates_collection_error_and_never_formats_partial_data(
        self, _mock_config, mock_fetch
    ):
        from adapty_ab_dashboard import AdaptyDashboardError
        from ab_test_report import build_ab_test_report

        mock_fetch.side_effect = AdaptyDashboardError("authentication failed")
        with self.assertRaises(AdaptyDashboardError):
            build_ab_test_report()

    @patch("ab_test_report.AdaptyAbDashboardClient")
    def test_fetch_delegates_to_experiment_scoped_dashboard_client(self, mock_client_cls):
        from adapty_ab_dashboard import AdaptyAbMetrics, AdaptyAbVariantMetrics
        from ab_test_report import fetch_ab_test_metrics

        mock_client_cls.return_value.fetch_metrics.return_value = AdaptyAbMetrics(
            test_id="test-123",
            test_name="Price test",
            variants=(
                AdaptyAbVariantMetrics("A", "old-paywall", "Old", 1, 2, 3, 4),
                AdaptyAbVariantMetrics("B", "new-paywall", "New", 5, 6, 7, 8),
            ),
            collected_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        )
        config = _enabled_config()

        result = fetch_ab_test_metrics(config, date(2026, 7, 17))

        mock_client_cls.assert_called_once_with(
            app_id="app-456",
            token="Bearer dashboard-secret",
        )
        mock_client_cls.return_value.fetch_metrics.assert_called_once_with(
            test_id="test-123",
            expected_test_name=config.test_name,
            expected_variants={
                "A": ("old-paywall", "New Paywall Old Prices"),
                "B": ("new-paywall", "New Paywall New Prices"),
            },
        )
        self.assertEqual(result.collected_at, datetime(2026, 7, 17, tzinfo=timezone.utc))
        self.assertEqual([row.label for row in result.rows], ["A", "B"])

    @patch("ab_test_report.get_adapty_apps")
    @patch("ab_test_report.get_ab_test_variant_value")
    @patch("ab_test_report.get_adapty_dashboard_token", return_value="")
    @patch("ab_test_report.get_adapty_dashboard_app_id", return_value="app-456")
    @patch("ab_test_report.get_ab_test_id", return_value="test-123")
    @patch("ab_test_report.get_ab_test_start_date", return_value="2026-07-10")
    @patch("ab_test_report.get_ab_test_name", return_value="Price test")
    @patch("ab_test_report.is_ab_test_report_enabled", return_value=True)
    def test_enabled_config_requires_dashboard_token(
        self,
        _mock_enabled,
        _mock_name,
        _mock_start,
        _mock_test_id,
        _mock_app_id,
        _mock_token,
        _mock_variant,
        _mock_apps,
    ):
        from ab_test_report import get_ab_test_config

        with self.assertRaisesRegex(ValueError, "ADAPTY_DASHBOARD_TOKEN"):
            get_ab_test_config()


if __name__ == "__main__":
    unittest.main()
