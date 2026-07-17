"""Tests for the strict Secret-Key A/B Telegram report."""
from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import patch

from config import AppConfig


APPROVED_APP_NAME = "Unfollowers: Follow & Unfollow"
APPROVED_TEST_NAME = "Test paywall prices. 4.99/29.99 vs 5.99/39.99"
APPROVED_TEST_ID = "1db6e378-026f-4634-9522-ec4fa95deb99"
APPROVED_START_DATE = date(2026, 7, 10)
APPROVED_OLD_PAYWALL_ID = "d6d24875-e330-4ad9-8ee0-841d3452a911"
APPROVED_NEW_PAYWALL_ID = "d6765d7f-eb06-42db-8d0d-ee21e2b41fe8"


def _enabled_config():
    from ab_test_report import AbTestConfig, AbTestVariantConfig

    return AbTestConfig(
        enabled=True,
        app_index=1,
        app_name=APPROVED_APP_NAME,
        test_name=APPROVED_TEST_NAME,
        start_date=APPROVED_START_DATE,
        variant_a=AbTestVariantConfig(
            "A", APPROVED_OLD_PAYWALL_ID, "New Paywall Old Prices"
        ),
        variant_b=AbTestVariantConfig(
            "B", APPROVED_NEW_PAYWALL_ID, "New Paywall New Prices"
        ),
        test_id=APPROVED_TEST_ID,
    )


def _metrics(label, paywall_id, revenue, unique_views, purchases, arpas):
    from adapty_ab_export import AdaptyAbVariantMetrics

    return AdaptyAbVariantMetrics(
        label=label,
        paywall_id=paywall_id,
        revenue=revenue,
        unique_views=unique_views,
        purchases=purchases,
        arpas=arpas,
    )


class TestAbTestReport(unittest.TestCase):
    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config)
    def test_formats_exact_approved_unique_view_report(self, _mock_config, mock_fetch):
        from ab_test_report import build_ab_test_report

        mock_fetch.return_value = [
            _metrics(
                "A", APPROVED_OLD_PAYWALL_ID, 86.11157593263285, 570, 9,
                9.56795288140365,
            ),
            _metrics(
                "B", APPROVED_NEW_PAYWALL_ID, 163.2467, 573, 19,
                8.591931578947368,
            ),
        ]

        expected = """🧪 A/B Test: Test paywall prices. 4.99/29.99 vs 5.99/39.99
📱 App: Unfollowers: Follow &amp; Unfollow

🅰️ <b>A / New Paywall Old Prices</b>
💵 Revenue: $86.11
📈 ARPAS: $9.57
👥 Unique paywall views: 570
💳 Purchases: 9
🔄 CR unique view→purchase: 1.58%

🅱️ <b>B / New Paywall New Prices</b>
💵 Revenue: $163.25
📈 ARPAS: $8.59
👥 Unique paywall views: 573
💳 Purchases: 19
🔄 CR unique view→purchase: 3.32%

🏆 Лидер по revenue: B (+$77.14)"""

        self.assertEqual(build_ab_test_report(date(2026, 7, 17)), expected)

    @patch("ab_test_report.AdaptyAbExportClient")
    @patch("ab_test_report.get_adapty_apps")
    def test_fetches_a_then_b_with_selected_app_secret_key(self, mock_apps, mock_client_cls):
        from ab_test_report import fetch_ab_test_metrics

        mock_apps.return_value = [AppConfig("secret-key", APPROVED_APP_NAME)]
        mock_client_cls.return_value.fetch_variant.side_effect = [
            _metrics("A", APPROVED_OLD_PAYWALL_ID, 1.0, 2, 1, 1.0),
            _metrics("B", APPROVED_NEW_PAYWALL_ID, 2.0, 3, 1, 2.0),
        ]
        config = _enabled_config()

        rows = fetch_ab_test_metrics(config, date(2026, 7, 17))

        mock_client_cls.assert_called_once_with(
            api_key="secret-key",
            base_url=unittest.mock.ANY,
            analytics_path=unittest.mock.ANY,
            timezone=unittest.mock.ANY,
        )
        self.assertEqual([row.label for row in rows], ["A", "B"])
        self.assertEqual(
            mock_client_cls.return_value.fetch_variant.call_args_list[0].kwargs,
            {
                "label": "A",
                "paywall_id": APPROVED_OLD_PAYWALL_ID,
                "test_id": APPROVED_TEST_ID,
                "start_date": APPROVED_START_DATE,
                "end_date": date(2026, 7, 17),
            },
        )
        self.assertEqual(
            mock_client_cls.return_value.fetch_variant.call_args_list[1].kwargs,
            {
                "label": "B",
                "paywall_id": APPROVED_NEW_PAYWALL_ID,
                "test_id": APPROVED_TEST_ID,
                "start_date": APPROVED_START_DATE,
                "end_date": date(2026, 7, 17),
            },
        )
        self.assertEqual(mock_client_cls.return_value.fetch_variant.call_count, 2)

    @patch("ab_test_report.AdaptyAbExportClient")
    @patch(
        "ab_test_report.get_adapty_apps",
        return_value=[AppConfig("secret-key", APPROVED_APP_NAME)],
    )
    def test_report_date_before_start_rejects_before_constructing_client(
        self, _mock_apps, mock_client_cls
    ):
        from ab_test_report import fetch_ab_test_metrics

        mock_client_cls.return_value.fetch_variant.side_effect = AssertionError(
            "collection must not begin"
        )

        with self.assertRaisesRegex(ValueError, "cannot precede"):
            fetch_ab_test_metrics(_enabled_config(), date(2026, 7, 9))
        mock_client_cls.assert_not_called()

    @patch("ab_test_report.AdaptyAbExportClient")
    @patch(
        "ab_test_report.get_adapty_apps",
        return_value=[AppConfig("", APPROVED_APP_NAME)],
    )
    def test_missing_selected_secret_key_raises_before_collection(
        self, _mock_apps, mock_client_cls
    ):
        from ab_test_report import fetch_ab_test_metrics

        with self.assertRaisesRegex(ValueError, "Secret API Key"):
            fetch_ab_test_metrics(_enabled_config(), date(2026, 7, 17))
        mock_client_cls.assert_not_called()

    @patch(
        "ab_test_report.get_adapty_apps",
        return_value=[AppConfig("secret-key", APPROVED_APP_NAME)],
    )
    def test_client_error_propagates_without_formatting_partial_data(self, _mock_apps):
        from adapty_ab_export import AdaptyAbExportError
        from ab_test_report import build_ab_test_report

        with patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config), patch(
            "ab_test_report.AdaptyAbExportClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_variant.side_effect = AdaptyAbExportError(
                "request failed"
            )
            with self.assertRaises(AdaptyAbExportError):
                build_ab_test_report(date(2026, 7, 17))

    @patch("ab_test_report.AdaptyAbExportClient")
    @patch(
        "ab_test_report.get_adapty_apps",
        return_value=[AppConfig("secret-key", APPROVED_APP_NAME)],
    )
    def test_reversed_client_labels_are_rejected(self, _mock_apps, mock_client_cls):
        from ab_test_report import fetch_ab_test_metrics

        mock_client_cls.return_value.fetch_variant.side_effect = [
            _metrics("B", APPROVED_OLD_PAYWALL_ID, 1.0, 1, 1, 1.0),
            _metrics("A", APPROVED_NEW_PAYWALL_ID, 1.0, 1, 1, 1.0),
        ]
        with self.assertRaisesRegex(ValueError, "A then B"):
            fetch_ab_test_metrics(_enabled_config(), date(2026, 7, 17))

    def test_zero_unique_views_formats_zero_conversion_without_division_by_zero(self):
        from ab_test_report import build_ab_test_report

        rows = [
            _metrics("A", APPROVED_OLD_PAYWALL_ID, 0.0, 0, 0, 0.0),
            _metrics("B", APPROVED_NEW_PAYWALL_ID, 1.0, 1, 1, 1.0),
        ]
        with patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config), patch(
            "ab_test_report.fetch_ab_test_metrics", return_value=rows
        ):
            self.assertIn("CR unique view→purchase: 0.00%", build_ab_test_report())

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config")
    def test_disabled_report_does_not_call_adapty(self, mock_config, mock_fetch):
        from ab_test_report import AbTestConfig, AbTestVariantConfig, build_ab_test_report

        empty = AbTestVariantConfig("", "", "")
        mock_config.return_value = AbTestConfig(
            False, 1, "", "", date.today(), empty, empty
        )

        self.assertIsNone(build_ab_test_report())
        mock_fetch.assert_not_called()

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config", side_effect=_enabled_config)
    def test_partial_rows_are_rejected_before_formatting(self, _mock_config, mock_fetch):
        from ab_test_report import build_ab_test_report

        mock_fetch.return_value = [
            _metrics("A", APPROVED_OLD_PAYWALL_ID, 1.0, 1, 1, 1.0)
        ]
        with self.assertRaisesRegex(ValueError, "exactly two"):
            build_ab_test_report()

    def _assert_config_rejected_before_client(self, config):
        from ab_test_report import fetch_ab_test_metrics

        apps = [AppConfig("secret-key", APPROVED_APP_NAME)]
        if config.app_index > 1:
            apps.append(AppConfig("another-key", "Another App"))
        with patch("ab_test_report.get_adapty_apps", return_value=apps), patch(
            "ab_test_report.AdaptyAbExportClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.fetch_variant.side_effect = [
                _metrics(
                    config.variant_a.label,
                    config.variant_a.paywall_id,
                    1.0,
                    1,
                    1,
                    1.0,
                ),
                _metrics(
                    config.variant_b.label,
                    config.variant_b.paywall_id,
                    2.0,
                    1,
                    1,
                    2.0,
                ),
            ]
            with self.assertRaisesRegex(ValueError, "approved production experiment"):
                fetch_ab_test_metrics(config, date(2026, 7, 17))
            mock_client_cls.assert_not_called()

    def test_swapped_paywall_ids_are_rejected_before_client(self):
        config = _enabled_config()
        self._assert_config_rejected_before_client(
            replace(
                config,
                variant_a=replace(
                    config.variant_a, paywall_id=APPROVED_NEW_PAYWALL_ID
                ),
                variant_b=replace(
                    config.variant_b, paywall_id=APPROVED_OLD_PAYWALL_ID
                ),
            )
        )

    def test_swapped_paywall_names_are_rejected_before_client(self):
        config = _enabled_config()
        self._assert_config_rejected_before_client(
            replace(
                config,
                variant_a=replace(
                    config.variant_a, paywall_name="New Paywall New Prices"
                ),
                variant_b=replace(
                    config.variant_b, paywall_name="New Paywall Old Prices"
                ),
            )
        )

    def test_wrong_variant_label_is_rejected_before_client(self):
        config = _enabled_config()
        self._assert_config_rejected_before_client(
            replace(config, variant_a=replace(config.variant_a, label="B"))
        )

    def test_wrong_test_id_is_rejected_before_client(self):
        self._assert_config_rejected_before_client(
            replace(_enabled_config(), test_id="another-experiment")
        )

    def test_wrong_start_date_is_rejected_before_client(self):
        self._assert_config_rejected_before_client(
            replace(_enabled_config(), start_date=date(2026, 7, 11))
        )

    def test_wrong_app_index_is_rejected_before_client(self):
        self._assert_config_rejected_before_client(
            replace(_enabled_config(), app_index=2)
        )

    def test_wrong_app_name_is_rejected_before_client(self):
        self._assert_config_rejected_before_client(
            replace(_enabled_config(), app_name="Another App")
        )

    @patch("ab_test_report.fetch_ab_test_metrics")
    @patch("ab_test_report.get_ab_test_config")
    def test_wrong_test_name_is_rejected_before_collection_or_formatting(
        self, mock_config, mock_fetch
    ):
        from ab_test_report import build_ab_test_report

        mock_config.return_value = replace(
            _enabled_config(), test_name="Another price test"
        )
        mock_fetch.side_effect = AssertionError("collection must not begin")

        with self.assertRaisesRegex(ValueError, "approved production experiment"):
            build_ab_test_report(date(2026, 7, 17))
        mock_fetch.assert_not_called()

    @patch("ab_test_report.get_adapty_apps")
    @patch("ab_test_report.get_ab_test_app_index", return_value=1)
    @patch("ab_test_report.get_ab_test_variant_value")
    @patch("ab_test_report.get_ab_test_id", return_value=APPROVED_TEST_ID)
    @patch(
        "ab_test_report.get_ab_test_start_date",
        return_value=APPROVED_START_DATE.isoformat(),
    )
    @patch("ab_test_report.get_ab_test_name", return_value=APPROVED_TEST_NAME)
    @patch("ab_test_report.is_ab_test_report_enabled", return_value=True)
    def test_enabled_config_requires_explicit_variant_label(
        self,
        _mock_enabled,
        _mock_name,
        _mock_start,
        _mock_test_id,
        mock_variant,
        _mock_app_index,
        mock_apps,
    ):
        from ab_test_report import get_ab_test_config

        mock_apps.return_value = [AppConfig("secret-key", APPROVED_APP_NAME)]
        mock_variant.side_effect = lambda variant, field: {
            ("A", "LABEL"): "",
            ("A", "PAYWALL_ID"): APPROVED_OLD_PAYWALL_ID,
            ("A", "PAYWALL_NAME"): "New Paywall Old Prices",
            ("B", "LABEL"): "B",
            ("B", "PAYWALL_ID"): APPROVED_NEW_PAYWALL_ID,
            ("B", "PAYWALL_NAME"): "New Paywall New Prices",
        }[(variant, field)]

        with self.assertRaisesRegex(ValueError, "AB_TEST_VARIANT_A_LABEL"):
            get_ab_test_config()

    @patch(
        "ab_test_report.get_adapty_apps",
        return_value=[AppConfig("secret-key", APPROVED_APP_NAME)],
    )
    @patch("ab_test_report.get_ab_test_variant_value")
    @patch("ab_test_report.get_ab_test_id", return_value=APPROVED_TEST_ID)
    @patch(
        "ab_test_report.get_ab_test_start_date",
        return_value=APPROVED_START_DATE.isoformat(),
    )
    @patch("ab_test_report.get_ab_test_name", return_value=APPROVED_TEST_NAME)
    @patch("ab_test_report.is_ab_test_report_enabled", return_value=True)
    def test_enabled_config_rejects_duplicate_paywall_ids(
        self,
        _mock_enabled,
        _mock_name,
        _mock_start,
        _mock_test_id,
        mock_variant,
        _mock_apps,
    ):
        from ab_test_report import get_ab_test_config

        mock_variant.side_effect = lambda variant, field: {
            ("A", "LABEL"): "A",
            ("A", "PAYWALL_ID"): "same-paywall",
            ("A", "PAYWALL_NAME"): "Old",
            ("B", "LABEL"): "B",
            ("B", "PAYWALL_ID"): "same-paywall",
            ("B", "PAYWALL_NAME"): "New",
        }[(variant, field)]

        with self.assertRaisesRegex(ValueError, "different"):
            get_ab_test_config()


if __name__ == "__main__":
    unittest.main()
