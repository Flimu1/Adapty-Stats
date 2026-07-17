"""
Tests for configuration precedence.
"""
import unittest
from unittest.mock import mock_open, patch


class TestConfig(unittest.TestCase):
    @patch.dict(
        "config.os.environ",
        {
            "AB_TEST_ID": "test-123",
            "ADAPTY_DASHBOARD_APP_ID": "app-456",
            "ADAPTY_DASHBOARD_TOKEN": "Bearer dashboard-secret",
        },
        clear=False,
    )
    def test_ab_dashboard_identity_is_read_from_env(self):
        from config import (
            get_ab_test_id,
            get_adapty_dashboard_app_id,
            get_adapty_dashboard_token,
        )

        self.assertEqual(get_ab_test_id(), "test-123")
        self.assertEqual(get_adapty_dashboard_app_id(), "app-456")
        self.assertEqual(get_adapty_dashboard_token(), "Bearer dashboard-secret")

    @patch("config.os.path.isfile", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="09:00")
    @patch.dict("config.os.environ", {"REPORT_TIME": "23:59"}, clear=False)
    def test_report_time_env_overrides_runtime_file(self, _mock_file, _mock_isfile):
        from config import get_report_time

        self.assertEqual(get_report_time(), "23:59")

    @patch.dict("config.os.environ", {"APPLE_ADS_START_DATE": "2026-06-01"}, clear=False)
    def test_apple_ads_start_date_is_read_from_env(self):
        from config import get_apple_ads_start_date

        self.assertEqual(get_apple_ads_start_date(), "2026-06-01")

    @patch.dict("config.os.environ", {"APPLE_ADS_APP_INDEX": "2"}, clear=False)
    def test_apple_ads_app_index_is_read_from_env(self):
        from config import get_apple_ads_app_index

        self.assertEqual(get_apple_ads_app_index(), 2)

    @patch.dict("config.os.environ", {"APPLE_ADS_APP_INDEX": "0"}, clear=False)
    def test_apple_ads_app_index_must_be_positive(self):
        from config import get_apple_ads_app_index

        with self.assertRaises(ValueError):
            get_apple_ads_app_index()


if __name__ == "__main__":
    unittest.main()
