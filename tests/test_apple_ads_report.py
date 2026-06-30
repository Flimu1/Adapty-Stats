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
    @patch("apple_ads_report._fetch_adapty_asa_metrics")
    @patch("apple_ads_report._fetch_apple_ads_campaign_totals")
    def test_fetch_apple_ads_metrics_uses_only_ads_manager_values(
        self,
        mock_apple_totals,
        mock_asa_metrics,
        mock_apps,
    ):
        from config import AppConfig
        from apple_ads_report import fetch_apple_ads_metrics

        mock_apps.return_value = [AppConfig(api_key="secret", name="Unfollowers")]
        mock_asa_metrics.return_value = {"spend": 1.17, "revenue": 0.0, "installs": 0, "paid": 0}
        mock_apple_totals.return_value = {"spend": 120.0, "installs": 240.0}

        metrics = fetch_apple_ads_metrics(_enabled_config(), date(2026, 6, 4))

        self.assertEqual(metrics.spend, 1.17)
        self.assertEqual(metrics.revenue, 0.0)
        self.assertEqual(metrics.installs, 0)
        self.assertEqual(metrics.paid, 0)
        mock_apple_totals.assert_not_called()

    @patch("apple_ads_report.get_adapty_apps")
    @patch("apple_ads_report._fetch_adapty_asa_metrics", return_value=None)
    @patch("apple_ads_report._fetch_apple_ads_campaign_totals")
    def test_fetch_apple_ads_metrics_returns_none_when_all_sources_are_unavailable(
        self,
        mock_apple_totals,
        _mock_asa_metrics,
        mock_apps,
    ):
        from config import AppConfig
        from apple_ads_report import fetch_apple_ads_metrics

        mock_apps.return_value = [AppConfig(api_key="secret", name="Unfollowers")]
        mock_apple_totals.return_value = {"spend": None, "installs": None}

        metrics = fetch_apple_ads_metrics(_enabled_config(), date(2026, 6, 4))

        self.assertIsNone(metrics)
        mock_apple_totals.assert_called_once()

    @patch("apple_ads_report.get_adapty_apps")
    @patch("apple_ads_report._fetch_adapty_asa_metrics", return_value=None)
    @patch("apple_ads_report._fetch_apple_ads_campaign_totals")
    def test_fetch_apple_ads_metrics_uses_apple_ads_fallback_when_asa_is_unavailable(
        self,
        mock_apple_totals,
        _mock_asa_metrics,
        mock_apps,
    ):
        from config import AppConfig
        from apple_ads_report import fetch_apple_ads_metrics

        mock_apps.return_value = [AppConfig(api_key="secret", name="Unfollowers")]
        mock_apple_totals.return_value = {"spend": 120.0, "installs": 240.0}

        metrics = fetch_apple_ads_metrics(_enabled_config(), date(2026, 6, 4))

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.spend, 120.0)
        self.assertIsNone(metrics.revenue)
        self.assertEqual(metrics.installs, 240)
        self.assertIsNone(metrics.paid)

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
    def test_build_apple_ads_report_returns_diagnostic_when_metrics_unavailable(self, _mock_config, mock_fetch):
        from apple_ads_report import build_apple_ads_report

        mock_fetch.return_value = None

        self.assertEqual(
            build_apple_ads_report(report_date=date(2026, 6, 4)),
            "📣 Apple Ads — Unfollowers\n"
            "Data unavailable. Check Adapty ASA / Apple Ads credentials in logs.",
        )

    @patch("apple_ads_report.fetch_apple_ads_metrics")
    @patch("apple_ads_report.get_apple_ads_report_config", side_effect=_enabled_config)
    def test_build_apple_ads_report_formats_zero_ads_values(self, _mock_config, mock_fetch):
        from apple_ads_report import AppleAdsMetrics, build_apple_ads_report

        mock_fetch.return_value = AppleAdsMetrics(
            spend=1.17,
            revenue=0.0,
            installs=0,
            paid=0,
        )

        text = build_apple_ads_report(report_date=date(2026, 6, 15))

        self.assertEqual(
            text,
            "📣 Apple Ads — Unfollowers\n"
            "Spend $1.17 | Revenue $0 | ROAS 0%\n"
            "Installs 0 | Paid 0 | CPI $0 | CPA $0",
        )

    def test_extracts_adapty_asa_overview_payload(self):
        from apple_ads_report import _extract_asa_metrics

        payload = {
            "data": {
                "performanceSpend": {"total": {"amount": 1.17, "currency": "USD"}},
                "conversionsRevenue": {"total": {"amount": 0, "currency": "USD"}},
                "conversionsInstalls": {"total": 0},
                "conversionsPaid": {"total": 0},
            }
        }

        self.assertEqual(
            _extract_asa_metrics(payload),
            {"spend": 1.17, "revenue": 0.0, "installs": 0.0, "paid": 0.0},
        )

    def test_extracts_real_adapty_asa_nested_payload(self):
        from apple_ads_report import _extract_asa_metrics

        payload = {
            "data": {
                "local_spend": {"common": {"value": "1.1667"}},
                "revenue": {"gross": {"total": {"value": "0"}}},
                "adapty_installs": {"common": {"value": "0"}},
                "paid": {"common": {"value": "0"}},
            }
        }

        self.assertEqual(
            _extract_asa_metrics(payload),
            {"spend": 1.1667, "revenue": 0.0, "installs": 0.0, "paid": 0.0},
        )

    def test_extracts_adapty_asa_net_revenue_like_dashboard(self):
        from apple_ads_report import _extract_asa_metrics

        payload = {
            "data": {
                "revenue": {
                    "gross": {"total": {"value": "194.67"}},
                    "proceeds": {"total": {"value": "165.47"}},
                    "net": {"total": {"value": "148.76"}},
                },
                "local_spend": {"common": {"value": "288.80"}},
                "adapty_installs": {"common": {"value": "983"}},
                "paid": {"common": {"value": "21"}},
            }
        }

        self.assertEqual(
            _extract_asa_metrics(payload),
            {"spend": 288.80, "revenue": 148.76, "installs": 983.0, "paid": 21.0},
        )


if __name__ == "__main__":
    unittest.main()
