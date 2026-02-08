"""
Тест формата отчёта и расчёта Total MRR / Total Downloads.
Запуск из корня: python -m pytest tests/test_report_builder.py -v
или: python tests/test_report_builder.py
"""
import unittest
from unittest.mock import patch


def _mock_fetch_all_metrics():
    """Мок: два приложения с известными суммами для проверки Total."""
    return [
        {
            "name": "App One",
            "mrr_total": 1000.5,
            "mrr_delta_24h": 50.25,
            "installs_total": 5000,
            "installs_delta_24h": 120,
        },
        {
            "name": "App Two",
            "mrr_total": 2000.0,
            "mrr_delta_24h": -10.5,
            "installs_total": 3000,
            "installs_delta_24h": 80,
        },
    ]


class TestReportBuilder(unittest.TestCase):
    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_report_contains_total_section(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        self.assertIn("<b>Total</b>", text)
        self.assertIn("Total MRR", text)
        self.assertIn("Total Downloads", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_mrr_is_sum_of_current_mrr(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 1000.5 + 2000 = 3000.5 → формат $3,000.50
        self.assertIn("3,000.50", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_mrr_delta_in_parentheses(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 50.25 + (-10.5) = 39.75 → (+$39.75)
        self.assertIn("+$39.75", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_total_downloads_is_sum_of_deltas(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        # 120 + 80 = 200 → (+200)
        self.assertIn("+200", text)

    @patch("report_builder.fetch_all_metrics", side_effect=_mock_fetch_all_metrics)
    def test_app_blocks_present(self, _mock_fetch):
        from report_builder import build_report_text

        text = build_report_text()
        self.assertIn("<b>App One</b>", text)
        self.assertIn("<b>App Two</b>", text)
        self.assertIn("💰 MRR:", text)
        self.assertIn("📲 Installs:", text)


if __name__ == "__main__":
    unittest.main()
