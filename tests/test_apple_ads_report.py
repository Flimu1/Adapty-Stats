"""
Tests for the compact Apple Ads Telegram report.
"""
from datetime import date
import unittest
from unittest.mock import patch


def _enabled_config():
    from apple_ads_report import AppleAdsReportConfig

    return AppleAdsReportConfig(
        enabled=True,
        app_index=1,
        app_name="Unfollowers: Follow & Unfollow",
        report_title="Unfollowers",
        start_date=date(2026, 6, 1),
        attribution_source="apple_search_ads",
    )


class TestAppleAdsReport(unittest.TestCase):
    @patch("apple_ads_report.fetch_apple_ads_metrics")
    @patch("apple_ads_report.get_apple_ads_report_config", side_effect=_enabled_config)
    def test_build_apple_ads_report_formats_short_message(self, _mock_config, mock_fetch):
        from apple_ads_report import AppleAdsMetrics, build_apple_ads_report

        mock_fetch.return_value = AppleAdsMetrics(
            spend=120.0,
            revenue=180.0,
            installs=240,
            paid=12,
        )

        text = build_apple_ads_report(report_date=date(2026, 6, 4))

        self.assertEqual(
            text,
            "📣 Apple Ads — Unfollowers\n"
            "Spend $120 | Revenue $180 | ROAS 150%\n"
            "Installs 240 | Paid 12 | CPI $0.50 | CPA $10",
        )

    def test_metrics_calculates_roas_cpi_and_cpa(self):
        from apple_ads_report import AppleAdsMetrics

        metrics = AppleAdsMetrics(spend=120.0, revenue=180.0, installs=240, paid=12)

        self.assertEqual(metrics.roas, 150.0)
        self.assertEqual(metrics.cpi, 0.5)
        self.assertEqual(metrics.cpa, 10.0)

    @patch("apple_ads_report.get_adapty_apps")
    @patch("apple_ads_report.get_adapty_base_url", return_value="https://api-admin.adapty.io")
    @patch("apple_ads_report.get_adapty_analytics_path", return_value="api/v1/client-api/metrics/analytics/")
    @patch("apple_ads_report.get_adapty_timezone", return_value="Europe/Minsk")
    @patch("apple_ads_report._fetch_ads_manager_metrics")
    @patch("apple_ads_report._fetch_apple_ads_campaign_totals")
    @patch("apple_ads_report._fetch_analytics_chart")
    def test_fetch_apple_ads_metrics_uses_apple_api_spend_fallback(
        self,
        mock_analytics,
        mock_apple_totals,
        mock_ads_manager,
        _mock_tz,
        _mock_path,
        _mock_base_url,
        mock_apps,
    ):
        from config import AppConfig
        from apple_ads_report import fetch_apple_ads_metrics

        mock_apps.return_value = [AppConfig(api_key="secret", name="Unfollowers")]
        mock_ads_manager.return_value = {
            "spend": None,
            "revenue": None,
            "installs": None,
            "paid": None,
        }
        mock_apple_totals.return_value = {"spend": 120.0, "installs": 240.0}
        mock_analytics.side_effect = [180.0, 240.0, 12.0]

        metrics = fetch_apple_ads_metrics(_enabled_config(), date(2026, 6, 4))

        self.assertEqual(metrics.spend, 120.0)
        self.assertEqual(metrics.revenue, 180.0)
        self.assertEqual(metrics.installs, 240)
        self.assertEqual(metrics.paid, 12)

    @patch("apple_ads_report.fetch_apple_ads_metrics")
    @patch("apple_ads_report.get_apple_ads_report_config")
    def test_build_apple_ads_report_returns_none_when_disabled(self, mock_config, mock_fetch):
        from apple_ads_report import AppleAdsReportConfig, build_apple_ads_report

        mock_config.return_value = AppleAdsReportConfig(
            enabled=False,
            app_index=1,
            app_name="",
            report_title="Unfollowers",
            start_date=date(2026, 6, 1),
            attribution_source="apple_search_ads",
        )

        self.assertIsNone(build_apple_ads_report(report_date=date(2026, 6, 4)))
        mock_fetch.assert_not_called()

    @patch("apple_ads_report.fetch_apple_ads_metrics")
    @patch("apple_ads_report.get_apple_ads_report_config", side_effect=_enabled_config)
    def test_build_apple_ads_report_handles_missing_data(self, _mock_config, mock_fetch):
        from apple_ads_report import AppleAdsMetrics, build_apple_ads_report

        mock_fetch.return_value = AppleAdsMetrics(
            spend=None,
            revenue=180.0,
            installs=None,
            paid=0,
        )

        text = build_apple_ads_report(report_date=date(2026, 6, 4))

        self.assertEqual(
            text,
            "📣 Apple Ads — Unfollowers\n"
            "Spend $N/A | Revenue $180 | ROAS N/A\n"
            "Installs N/A | Paid 0 | CPI N/A | CPA N/A",
        )


if __name__ == "__main__":
    unittest.main()
