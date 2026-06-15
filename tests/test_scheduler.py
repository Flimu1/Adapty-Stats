"""
Tests for daily scheduler send behavior.
"""
from datetime import date
import unittest
from unittest.mock import patch


class TestSchedulerDailyJob(unittest.TestCase):
    @patch("config.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("apple_ads_report.build_apple_ads_report", return_value="Apple Ads report")
    @patch("ab_test_report.build_ab_test_report", return_value="AB report")
    @patch("report_builder.build_report")
    def test_daily_job_sends_followup_reports_after_main_report(
        self,
        mock_build_report,
        _mock_ab_report,
        _mock_apple_ads_report,
        mock_send,
        _mock_admin,
    ):
        from report_builder import ReportBuildResult
        from scheduler import _send_daily_job

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
        )

        _send_daily_job()

        self.assertEqual(mock_send.call_args_list[0].args[0], "Main report")
        self.assertEqual(mock_send.call_args_list[1].args[0], "AB report")
        self.assertEqual(mock_send.call_args_list[2].args[0], "Apple Ads report")

    @patch("config.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("apple_ads_report.build_apple_ads_report", return_value="Apple Ads report")
    @patch("ab_test_report.build_ab_test_report", side_effect=RuntimeError("AB failed"))
    @patch("report_builder.build_report")
    def test_daily_job_keeps_main_and_apple_ads_when_ab_report_fails(
        self,
        mock_build_report,
        _mock_ab_report,
        _mock_apple_ads_report,
        mock_send,
        _mock_admin,
    ):
        from report_builder import ReportBuildResult
        from scheduler import _send_daily_job

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
        )

        _send_daily_job()

        self.assertEqual(mock_send.call_args_list[0].args[0], "Main report")
        self.assertEqual(mock_send.call_args_list[1].args[0], "Apple Ads report")

    @patch("config.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("apple_ads_report.build_apple_ads_report", side_effect=RuntimeError("Apple Ads failed"))
    @patch("ab_test_report.build_ab_test_report", return_value="AB report")
    @patch("report_builder.build_report")
    def test_daily_job_keeps_main_and_ab_when_apple_ads_report_fails(
        self,
        mock_build_report,
        _mock_ab_report,
        _mock_apple_ads_report,
        mock_send,
        _mock_admin,
    ):
        from report_builder import ReportBuildResult
        from scheduler import _send_daily_job

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
        )

        _send_daily_job()

        self.assertEqual(len(mock_send.call_args_list), 2)
        self.assertEqual(mock_send.call_args_list[0].args[0], "Main report")
        self.assertEqual(mock_send.call_args_list[1].args[0], "AB report")


if __name__ == "__main__":
    unittest.main()
