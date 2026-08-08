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
            integrity_problem_count=0,
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
            integrity_problem_count=0,
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
            integrity_problem_count=0,
        )

        _send_daily_job()

        self.assertEqual(len(mock_send.call_args_list), 2)
        self.assertEqual(mock_send.call_args_list[0].args[0], "Main report")
        self.assertEqual(mock_send.call_args_list[1].args[0], "AB report")

    @patch("telegram_sender.get_telegram_admin_id", return_value="42")
    @patch("telegram_sender.send_message", return_value=True)
    @patch("apple_ads_report.build_apple_ads_report", return_value="Apple Ads report")
    @patch("ab_test_report.build_ab_test_report", return_value="AB report")
    @patch("report_builder.build_report")
    def test_partial_daily_report_is_sent_with_followups_and_admin_details(
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
            text="Partial main report",
            report_date=date(2026, 8, 6),
            anomalies=["Otty: Revenue response is invalid"],
            integrity_problem_count=1,
        )

        _send_daily_job()

        sent_texts = [call.args[0] for call in mock_send.call_args_list]
        self.assertEqual(sent_texts[:3], [
            "Partial main report",
            "AB report",
            "Apple Ads report",
        ])
        admin_calls = [
            call for call in mock_send.call_args_list
            if call.kwargs.get("chat_id") == "42"
        ]
        self.assertEqual(len(admin_calls), 1)
        self.assertIn("Otty: Revenue response is invalid", admin_calls[0].args[0])


if __name__ == "__main__":
    unittest.main()
