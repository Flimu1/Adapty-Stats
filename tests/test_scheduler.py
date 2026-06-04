"""
Tests for daily scheduler send behavior.
"""
from datetime import date
import unittest
from unittest.mock import patch


class TestSchedulerDailyJob(unittest.TestCase):
    @patch("config.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("ab_test_report.build_ab_test_report", return_value="AB report")
    @patch("report_builder.build_report")
    def test_daily_job_sends_ab_report_after_main_report(
        self,
        mock_build_report,
        _mock_ab_report,
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

    @patch("config.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("ab_test_report.build_ab_test_report", side_effect=RuntimeError("AB failed"))
    @patch("report_builder.build_report")
    def test_daily_job_keeps_main_report_sent_when_ab_report_fails(
        self,
        mock_build_report,
        _mock_ab_report,
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

        self.assertEqual(len(mock_send.call_args_list), 1)
        self.assertEqual(mock_send.call_args_list[0].args[0], "Main report")


if __name__ == "__main__":
    unittest.main()
