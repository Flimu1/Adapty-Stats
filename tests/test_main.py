"""CLI behavior tests."""
import unittest
from unittest.mock import patch


class TestMainCli(unittest.TestCase):
    @patch("telegram_sender.send_ab_report_once", return_value=False)
    @patch("sys.argv", ["main.py", "--send-ab-report"])
    def test_send_ab_report_exits_nonzero_on_failure(self, mock_send):
        import main

        with self.assertRaises(SystemExit) as raised:
            main.main()

        self.assertEqual(raised.exception.code, 1)
        mock_send.assert_called_once_with()

    @patch("telegram_sender.send_ab_report_once", return_value=True)
    @patch("sys.argv", ["main.py", "--send-ab-report"])
    def test_send_ab_report_returns_normally_on_success(self, mock_send):
        import main

        main.main()
        mock_send.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
