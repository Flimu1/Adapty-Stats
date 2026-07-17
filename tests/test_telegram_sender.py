"""
Tests for Telegram sender helper behavior.
"""
import unittest
from unittest.mock import patch


class TestTelegramSender(unittest.TestCase):
    @patch("telegram_sender.get_telegram_topic_id", return_value=None)
    @patch("telegram_sender.get_telegram_chat_id", return_value="-100123")
    @patch("telegram_sender.get_telegram_token", return_value="123456:secret-token")
    @patch("telegram_sender.requests.post")
    def test_send_failure_does_not_log_token_or_request_url(
        self,
        mock_post,
        _mock_token,
        _mock_chat,
        _mock_topic,
    ):
        import requests
        from telegram_sender import send_message

        mock_post.side_effect = requests.ConnectionError(
            "failed https://api.telegram.org/bot123456:secret-token/sendMessage"
        )

        with self.assertLogs("telegram_sender", level="ERROR") as captured:
            self.assertFalse(send_message("hello"))

        output = "\n".join(captured.output)
        self.assertNotIn("123456:secret-token", output)
        self.assertNotIn("api.telegram.org", output)
        self.assertIn("ConnectionError", output)

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
