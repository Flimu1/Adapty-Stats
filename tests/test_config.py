"""
Tests for configuration precedence.
"""
import unittest
from unittest.mock import mock_open, patch


class TestConfig(unittest.TestCase):
    @patch("config.os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="09:00")
    @patch.dict("config.os.environ", {"REPORT_TIME": "23:59"}, clear=False)
    def test_report_time_env_overrides_runtime_file(self, _mock_file, _mock_isfile):
        from config import get_report_time

        self.assertEqual(get_report_time(), "23:59")


if __name__ == "__main__":
    unittest.main()
