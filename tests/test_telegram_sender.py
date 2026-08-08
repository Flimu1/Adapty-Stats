"""
Tests for Telegram sender helper behavior.
"""
import unittest
from unittest.mock import patch


class TestTelegramSender(unittest.TestCase):
    @patch("telegram_sender.send_message", return_value=True)
    @patch("ab_test_report.build_ab_test_report", return_value="Verified A/B report")
    def test_send_ab_report_once_sends_exactly_one_ab_message(
        self,
        mock_build,
        mock_send,
    ):
        from datetime import date
        from telegram_sender import send_ab_report_once

        report_date = date(2026, 7, 17)
        self.assertTrue(send_ab_report_once(report_date))

        mock_build.assert_called_once_with(report_date=report_date)
        mock_send.assert_called_once_with("Verified A/B report")

    @patch("telegram_sender.send_message")
    @patch("ab_test_report.build_ab_test_report", return_value=None)
    def test_send_ab_report_once_does_not_send_when_disabled(
        self,
        mock_build,
        mock_send,
    ):
        from telegram_sender import send_ab_report_once

        self.assertFalse(send_ab_report_once())
        mock_build.assert_called_once_with(report_date=None)
        mock_send.assert_not_called()

    @patch("telegram_sender.send_message")
    @patch("ab_test_report.build_ab_test_report", side_effect=RuntimeError("bad data"))
    def test_send_ab_report_once_does_not_send_on_build_error(
        self,
        _mock_build,
        mock_send,
    ):
        from telegram_sender import send_ab_report_once

        with self.assertLogs("telegram_sender", level="ERROR"):
            self.assertFalse(send_ab_report_once())
        mock_send.assert_not_called()

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
    @patch("telegram_sender.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_test_send_sends_main_report_to_group_and_followups(
        self,
        mock_build_report,
        mock_send,
        _mock_admin,
        mock_followups,
    ):
        from datetime import date
        from report_builder import ReportBuildResult
        from telegram_sender import test_send

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
            integrity_problem_count=0,
        )

        self.assertTrue(test_send())

        mock_send.assert_called_once_with("Main report")
        mock_followups.assert_called_once_with(date(2026, 6, 4))

    @patch("report_delivery.send_followup_reports")
    @patch("telegram_sender.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_test_send_skips_followups_when_main_report_send_fails(
        self,
        mock_build_report,
        mock_send,
        _mock_admin,
        mock_followups,
    ):
        from datetime import date
        from report_builder import ReportBuildResult
        from telegram_sender import test_send

        mock_build_report.return_value = ReportBuildResult(
            text="Main report",
            report_date=date(2026, 6, 4),
            anomalies=[],
            integrity_problem_count=0,
        )
        mock_send.return_value = False

        self.assertFalse(test_send())
        mock_send.assert_called_once_with("Main report")
        mock_followups.assert_not_called()

    @patch("report_delivery.send_followup_reports", return_value=(["A/B", "Apple Ads"], []))
    @patch("telegram_sender.get_telegram_admin_id", return_value="42")
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_test_send_delivers_partial_report_followups_and_integrity_alert(
        self,
        mock_build_report,
        mock_send,
        _mock_admin,
        mock_followups,
    ):
        from datetime import date
        from report_builder import ReportBuildResult
        from telegram_sender import test_send

        mock_build_report.return_value = ReportBuildResult(
            text="Partial main report",
            report_date=date(2026, 8, 6),
            anomalies=["Otty: Revenue invalid"],
            integrity_problem_count=1,
        )

        self.assertTrue(test_send())

        self.assertEqual(mock_send.call_args_list[0].args[0], "Partial main report")
        admin_calls = [
            call for call in mock_send.call_args_list
            if call.kwargs.get("chat_id") == "42"
        ]
        self.assertEqual(len(admin_calls), 1)
        self.assertIn("Otty: Revenue invalid", admin_calls[0].args[0])
        mock_followups.assert_called_once_with(date(2026, 8, 6))


if __name__ == "__main__":
    unittest.main()
