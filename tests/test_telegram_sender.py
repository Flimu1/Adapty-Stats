"""
Tests for Telegram sender helper behavior.
"""
import unittest
from unittest.mock import patch


class TestTelegramSender(unittest.TestCase):
    @patch("telegram_sender.build_report_text_for_test", return_value="Test report")
    @patch("telegram_sender.get_telegram_admin_id", return_value="12345")
    @patch("telegram_sender.send_message", return_value=True)
    def test_test_send_prefers_admin_chat_when_configured(
        self,
        mock_send,
        _mock_admin,
        _mock_report,
    ):
        from telegram_sender import test_send

        self.assertTrue(test_send())

        mock_send.assert_called_once_with("Test report", chat_id="12345")

    @patch("telegram_sender.build_report_text_for_test", return_value="Test report")
    @patch("telegram_sender.get_telegram_admin_id", return_value=None)
    @patch("telegram_sender.send_message", return_value=True)
    def test_test_send_does_not_fall_back_to_group_chat(
        self,
        mock_send,
        _mock_admin,
        _mock_report,
    ):
        from telegram_sender import test_send

        self.assertFalse(test_send())
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
