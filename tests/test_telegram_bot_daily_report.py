from datetime import date
import unittest
from unittest.mock import patch


class TestTelegramBotDailyReport(unittest.TestCase):
    @patch("report_delivery.send_followup_reports", return_value=([], []))
    @patch("telegram_sender.get_telegram_admin_id", return_value="42")
    @patch("telegram_sender.send_message", return_value=True)
    @patch("report_builder.build_report")
    def test_manual_collection_reports_integrity_count_and_sends_details(
        self,
        mock_build_report,
        mock_send,
        _mock_admin,
        _mock_followups,
    ):
        from report_builder import ReportBuildResult
        from telegram_bot import _collect_and_send

        mock_build_report.return_value = ReportBuildResult(
            text="Partial main report",
            report_date=date(2026, 8, 6),
            anomalies=[
                "Otty: Revenue invalid",
                "Granny Photos: Conversion invalid",
            ],
            integrity_problem_count=2,
        )

        ok, message = _collect_and_send(chat_id="42", to_group=True)

        self.assertTrue(ok)
        self.assertIn("Проблем проверки данных: 2", message)
        self.assertEqual(mock_send.call_args_list[0].args[0], "Partial main report")
        admin_calls = [
            call for call in mock_send.call_args_list
            if call.kwargs.get("chat_id") == "42"
        ]
        self.assertEqual(len(admin_calls), 1)
        self.assertIn("Granny Photos: Conversion invalid", admin_calls[0].args[0])

    @patch("report_builder.build_report", side_effect=RuntimeError("secret detail"))
    def test_manual_collection_does_not_return_raw_exception(self, _mock_build):
        from telegram_bot import _collect_and_send

        ok, message = _collect_and_send(chat_id="42", to_group=True)

        self.assertFalse(ok)
        self.assertNotIn("secret detail", message)


if __name__ == "__main__":
    unittest.main()
