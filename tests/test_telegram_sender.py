"""
Tests for Telegram sender helper behavior.
"""
import unittest
from unittest.mock import patch


class TestTelegramSender(unittest.TestCase):
    @patch("report_delivery.send_followup_reports", return_value=(["A/B", "Apple Ads"], []))
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_test_send_sends_main_report_to_group_and_followups(
        self,
        mock_build_report,
        mock_send,
        mock_followups,
    ):
        from datetime import date
        from report_builder import ReportBuildResult
        from telegram_sender import test_send

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
        )

        self.assertTrue(test_send())

        mock_send.assert_called_once_with("Main report")
        mock_followups.assert_called_once_with(date(2026, 6, 4))

    @patch("report_delivery.send_followup_reports")
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_test_send_skips_followups_when_main_report_send_fails(
        self,
        mock_build_report,
        mock_send,
        mock_followups,
    ):
        from datetime import date
        from report_builder import ReportBuildResult
        from telegram_sender import test_send

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
        )
        mock_send.return_value = False

        self.assertFalse(test_send())
        mock_send.assert_called_once_with("Main report")
        mock_followups.assert_not_called()


if __name__ == "__main__":
    unittest.main()
