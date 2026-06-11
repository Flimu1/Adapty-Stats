"""
Tests for the A/B test Telegram overview report.
"""
from datetime import date
import unittest
from unittest.mock import patch


def _mock_enabled_config():
    from ab_test_report import AbTestConfig, AbTestVariantConfig

    return AbTestConfig(
        enabled=True,
        app_index=1,
        app_name="Unfollowers: Follow & Unfollow",
        test_name="Unfollowers: Follow & Unfollow",
        start_date=date(2026, 6, 1),
        variant_a=AbTestVariantConfig(
            label="Variant A",
            paywall_id="paywall_a",
            paywall_name="Old Paywall",
        ),
        variant_b=AbTestVariantConfig(
            label="Variant B",
            paywall_id="paywall_b",
            paywall_name="New Paywall",
        ),
    )


def _mock_metrics(_config, report_date):
    from ab_test_report import AbTestVariantMetrics

    assert report_date == date(2026, 6, 4)
    return [
        AbTestVariantMetrics(
            label="Variant A",
            paywall_name="Old Paywall",
            revenue=1234.56,
            paywall_views=1200,
            purchases=18,
            arpas=1.03,
        ),
        AbTestVariantMetrics(
            label="Variant B",
            paywall_name="New Paywall",
            revenue=1500.0,
            paywall_views=1000,
            purchases=24,
            arpas=1.5,
        ),
    ]


class TestAbTestReport(unittest.TestCase):
    @patch("ab_test_report.fetch_ab_test_metrics", side_effect=_mock_metrics)
    @patch("ab_test_report.get_ab_test_config", side_effect=_mock_enabled_config)
    def test_build_ab_test_report_formats_variants_and_leader(self, _mock_config, _mock_fetch):
        from ab_test_report import build_ab_test_report

        text = build_ab_test_report(report_date=date(2026, 6, 4))

        self.assertIn("🧪 A/B Test: Unfollowers: Follow &amp; Unfollow", text)
        self.assertIn("📱 App: Unfollowers: Follow &amp; Unfollow", text)
        self.assertIn("<b>Variant A / Old Paywall</b>", text)
        self.assertIn("💵 Revenue: $1,234.56", text)
        self.assertIn("📈 ARPAS: $1.03", text)
        self.assertIn("📲 Paywall views: 1,200", text)
        self.assertIn("💳 Purchases: 18", text)
        self.assertIn("🔄 CR view→purchase: 1.50%", text)
        self.assertIn("<b>Variant B / New Paywall</b>", text)
        self.assertIn("💵 Revenue: $1,500", text)
        self.assertIn("📈 ARPAS: $1.50", text)
        self.assertIn("🔄 CR view→purchase: 2.40%", text)
        self.assertIn("🏆 Лидер по revenue: Variant B (+$265.44)", text)

    def test_variant_metrics_handles_zero_views_without_division_by_zero(self):
        from ab_test_report import AbTestVariantMetrics

        metrics = AbTestVariantMetrics(
            label="Variant A",
            paywall_name="Old Paywall",
            revenue=10.0,
            paywall_views=0,
            purchases=2,
        )

        self.assertIsNone(metrics.conversion_rate)

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config")
    def test_build_ab_test_report_returns_none_when_disabled(self, mock_config, mock_fetch):
        from ab_test_report import AbTestConfig, AbTestVariantConfig, build_ab_test_report

        mock_config.return_value = AbTestConfig(
            enabled=False,
            app_index=1,
            app_name="",
            test_name="Unfollowers: Follow & Unfollow",
            start_date=date(2026, 6, 1),
            variant_a=AbTestVariantConfig("Variant A", "a", "A"),
            variant_b=AbTestVariantConfig("Variant B", "b", "B"),
        )

        self.assertIsNone(build_ab_test_report(report_date=date(2026, 6, 4)))
        mock_fetch.assert_not_called()

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config", side_effect=_mock_enabled_config)
    def test_build_ab_test_report_shows_revenue_equal(self, _mock_config, mock_fetch):
        from ab_test_report import AbTestVariantMetrics, build_ab_test_report

        mock_fetch.return_value = [
            AbTestVariantMetrics("Variant A", "Old Paywall", 100.0, 10, 1),
            AbTestVariantMetrics("Variant B", "New Paywall", 100.0, 20, 3),
        ]

        text = build_ab_test_report(report_date=date(2026, 6, 4))

        self.assertIn("🤝 Revenue equal", text)

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config", side_effect=_mock_enabled_config)
    def test_build_ab_test_report_shows_arpas_na_when_missing(self, _mock_config, mock_fetch):
        from ab_test_report import AbTestVariantMetrics, build_ab_test_report

        mock_fetch.return_value = [
            AbTestVariantMetrics("Variant A", "Old Paywall", 100.0, 10, 1, None),
            AbTestVariantMetrics("Variant B", "New Paywall", 120.0, 20, 3, None),
        ]

        text = build_ab_test_report(report_date=date(2026, 6, 4))

        self.assertIn("📈 ARPAS: $N/A", text)

    def test_extract_arpas_prefers_total_row(self):
        from ab_test_report import _extract_arpas

        data = {
            "data": [
                {
                    "type": "segment",
                    "total_arpas_usd": 1.11,
                    "values": [{"arpas_usd": 1.22}],
                },
                {
                    "type": "total",
                    "total_arpas_usd": "2.34",
                    "values": [{"arpas_usd": 2.45}],
                },
            ]
        }

        self.assertEqual(_extract_arpas(data), 2.34)

    def test_extract_arpas_uses_first_row_total_without_total_row(self):
        from ab_test_report import _extract_arpas

        data = {
            "data": [
                {
                    "type": "paywall",
                    "total_arpas_usd": "1.23",
                    "values": [{"arpas_usd": 1.24}],
                }
            ]
        }

        self.assertEqual(_extract_arpas(data), 1.23)

    def test_extract_arpas_falls_back_to_last_value(self):
        from ab_test_report import _extract_arpas

        data = {
            "data": [
                {
                    "type": "paywall",
                    "values": [
                        {"period": 1, "arpas_usd": 1.0},
                        {"period": 2, "arpas_usd": "1.5"},
                    ],
                }
            ]
        }

        self.assertEqual(_extract_arpas(data), 1.5)

    def test_extract_arpas_returns_none_for_empty_or_invalid_data(self):
        from ab_test_report import _extract_arpas

        self.assertIsNone(_extract_arpas(None))
        self.assertIsNone(_extract_arpas({}))
        self.assertIsNone(_extract_arpas({"data": {}}))
        self.assertIsNone(_extract_arpas({"data": [{"values": [{"arpas_usd": "bad"}]}]}))


if __name__ == "__main__":
    unittest.main()
