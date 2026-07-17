"""CLI behavior tests."""
import unittest
from unittest.mock import patch


class TestMainCli(unittest.TestCase):
    @patch("ab_test_report.build_ab_test_report", return_value="preview")
    @patch("sys.argv", ["main.py", "--preview-ab-report"])
    def test_preview_ab_report_prints_once_without_sending_or_scheduling(self, mock_build):
        import main

        with (
            patch("builtins.print") as output,
            patch("telegram_sender.send_ab_report_once") as send,
            patch("scheduler.run_scheduler") as run_scheduler,
        ):
            main.main()

        output.assert_called_once_with("preview")
        mock_build.assert_called_once_with()
        send.assert_not_called()
        run_scheduler.assert_not_called()

    @patch("ab_test_report.build_ab_test_report", return_value=None)
    @patch("sys.argv", ["main.py", "--preview-ab-report"])
    def test_preview_ab_report_exits_nonzero_without_output_sending_or_scheduling(
        self, mock_build
    ):
        import main

        with (
            patch("builtins.print") as output,
            patch("telegram_sender.send_ab_report_once") as send,
            patch("scheduler.run_scheduler") as run_scheduler,
            self.assertRaises(SystemExit) as raised,
        ):
            main.main()

        self.assertEqual(raised.exception.code, 1)
        mock_build.assert_called_once_with()
        output.assert_not_called()
        send.assert_not_called()
        run_scheduler.assert_not_called()

    @patch("ab_test_report.build_ab_test_report", return_value="")
    @patch("sys.argv", ["main.py", "--preview-ab-report"])
    def test_preview_ab_report_empty_result_exits_nonzero_without_side_effects(
        self, mock_build
    ):
        import main

        with (
            patch("builtins.print") as output,
            patch("telegram_sender.send_ab_report_once") as send,
            patch("scheduler.run_scheduler") as run_scheduler,
            self.assertRaises(SystemExit) as raised,
        ):
            main.main()

        self.assertEqual(raised.exception.code, 1)
        mock_build.assert_called_once_with()
        output.assert_not_called()
        send.assert_not_called()
        run_scheduler.assert_not_called()

    @patch("ab_test_report.build_ab_test_report", return_value="preview")
    @patch("sys.argv", ["main.py", "--preview-ab-report", "--send-ab-report"])
    def test_preview_ab_report_takes_precedence_over_one_shot_send(self, mock_build):
        import main

        with (
            patch("builtins.print") as output,
            patch("telegram_sender.send_ab_report_once") as send,
        ):
            main.main()

        output.assert_called_once_with("preview")
        mock_build.assert_called_once_with()
        send.assert_not_called()

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
