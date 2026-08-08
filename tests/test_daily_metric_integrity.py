from datetime import date
import math
import unittest

from daily_report_contract import IntegrityIssue, MetricProvenance


def valid_row() -> dict:
    return {
        "index": 0,
        "name": "Unfollowers: Follow & Unfollow",
        "mrr_total": 100.0,
        "mrr_delta_24h": 5.0,
        "arr_total": 1200.0,
        "arr_delta_24h": 60.0,
        "revenue_total": 50.0,
        "revenue_per_day": 5.0,
        "installs_total": 100,
        "installs_delta_24h": 10,
        "conv_rate": 10.0,
        "conv_from": 100,
        "conv_to": 10,
        "issues": (),
        "is_visible": True,
    }


class TestDailyMetricValidation(unittest.TestCase):
    def test_revenue_refunds_remain_valid_source_values(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row["revenue_total"] = -10.0
        row["revenue_per_day"] = -11.0
        result = validate_app_metrics(row)

        self.assertEqual(result["revenue_total"], -10.0)
        self.assertEqual(result["revenue_per_day"], -11.0)
        self.assertEqual(result["issues"], ())

    def test_installs_inconsistency_quarantines_only_installs_family(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row["installs_total"] = 10
        row["installs_delta_24h"] = 11
        result = validate_app_metrics(row)

        self.assertIsNone(result["installs_total"])
        self.assertIsNone(result["installs_delta_24h"])
        self.assertEqual(result["revenue_total"], row["revenue_total"])

    def test_conversion_rate_must_reconcile_with_raw_counts(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row.update(conv_rate=9.0, conv_from=100, conv_to=10)
        result = validate_app_metrics(row)

        self.assertIsNone(result["conv_rate"])
        self.assertIsNone(result["conv_from"])
        self.assertIsNone(result["conv_to"])
        self.assertIn("conversion.ratio_mismatch", {i.code for i in result["issues"]})

    def test_invalid_numeric_types_are_quarantined(self):
        from daily_metric_integrity import validate_app_metrics

        for field, value in (
            ("mrr_total", True),
            ("arr_total", math.nan),
            ("revenue_total", math.inf),
            ("installs_total", 3.5),
        ):
            with self.subTest(field=field):
                row = valid_row()
                row[field] = value
                self.assertIsNone(validate_app_metrics(row)[field])

    def test_zero_conversion_is_valid_only_with_zero_paid_and_rate(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row.update(conv_rate=0.0, conv_from=0, conv_to=0)
        self.assertEqual(validate_app_metrics(row)["conv_rate"], 0.0)

        row.update(conv_rate=1.0, conv_from=0, conv_to=0)
        self.assertIsNone(validate_app_metrics(row)["conv_rate"])

    def test_paid_count_cannot_exceed_eligible_count(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row.update(conv_rate=100.0, conv_from=5, conv_to=6)
        result = validate_app_metrics(row)
        self.assertIsNone(result["conv_from"])
        self.assertIn("conversion.invalid_counts", {i.code for i in result["issues"]})

    def test_arr_value_mismatch_quarantines_arr_but_preserves_mrr(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row["arr_total"] = 1199.90
        result = validate_app_metrics(row)

        self.assertEqual(result["mrr_total"], 100.0)
        self.assertIsNone(result["arr_total"])
        self.assertIn("arr.mrr_multiple_mismatch", {i.code for i in result["issues"]})

    def test_arr_tolerance_accepts_rounding_noise(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row["arr_total"] = 1200.04
        self.assertEqual(validate_app_metrics(row)["arr_total"], 1200.04)

    def test_input_row_is_not_mutated(self):
        from daily_metric_integrity import validate_app_metrics

        row = valid_row()
        row["revenue_per_day"] = 100.0
        validate_app_metrics(row)
        self.assertEqual(row["revenue_total"], 50.0)
        self.assertEqual(row["revenue_per_day"], 100.0)
        self.assertEqual(row["issues"], ())


class TestDailyMetricAudit(unittest.TestCase):
    def test_root_fetch_issue_does_not_expand_into_repeated_field_problems(self):
        from daily_metric_integrity import REPORT_VALUE_FIELDS, validate_app_metrics

        root_issue = IntegrityIssue(
            code="fetch.failed",
            message="collection failed",
            app_name="Otty: Couples&Relationships",
        )
        row = {
            "index": 2,
            "name": "Otty: Couples&Relationships",
            **{field: None for field in REPORT_VALUE_FIELDS},
            "issues": (root_issue,),
            "is_visible": True,
        }

        result = validate_app_metrics(row)

        self.assertEqual(result["issues"], (root_issue,))

    def test_family_issue_code_is_attached_to_each_invalid_family_audit_field(self):
        from daily_metric_integrity import emit_integrity_audit, validate_app_metrics

        row = valid_row()
        row.update(
            revenue_total=None,
            revenue_per_day=None,
            issues=(IntegrityIssue(
                code="revenue.source_invalid",
                message="revenue source is invalid",
                app_name=row["name"],
                metric="revenue",
            ),),
        )

        with self.assertLogs("daily_metric_integrity", level="INFO") as captured:
            emit_integrity_audit(
                report_date=date(2026, 8, 6),
                timezone="Europe/Minsk",
                rows=(row,),
                total_status={},
                portfolio_issues=(),
            )

        revenue_lines = [line for line in captured.output if "metric=revenue_" in line]
        self.assertEqual(len(revenue_lines), 2)
        self.assertTrue(all("issue=revenue.source_invalid" in line for line in revenue_lines))

    def test_problem_count_deduplicates_issue_identity(self):
        from daily_metric_integrity import count_integrity_problems

        issue = IntegrityIssue(
            code="revenue.invalid",
            message="invalid",
            app_name="Granny Photos",
            metric="revenue_total",
        )
        row = valid_row()
        row.update(revenue_total=None, issues=(issue, issue))
        rows = (row,)
        portfolio_issue = IntegrityIssue(code="config.extra_slot", message="ignored")

        self.assertEqual(count_integrity_problems(rows, (portfolio_issue,)), 2)

    def test_problem_count_groups_quarantined_fields_into_metric_families(self):
        from daily_metric_integrity import count_integrity_problems

        row = valid_row()
        row.update(
            mrr_total=None,
            mrr_delta_24h=None,
            issues=(
                IntegrityIssue("mrr.total_invalid", "invalid", row["name"], "mrr_total"),
                IntegrityIssue("mrr.delta_invalid", "invalid", row["name"], "mrr_delta_24h"),
            ),
        )

        self.assertEqual(count_integrity_problems((row,), ()), 1)

    def test_problem_count_registers_all_families_for_blocked_slot(self):
        from daily_metric_integrity import REPORT_VALUE_FIELDS, count_integrity_problems

        row = {
            **valid_row(),
            **{field: None for field in REPORT_VALUE_FIELDS},
            "issues": (IntegrityIssue(
                "fetch.failed", "collection failed", "Unfollowers: Follow & Unfollow"
            ),),
        }

        self.assertEqual(count_integrity_problems((row,), ()), 5)

    def test_audit_logs_status_without_values_or_secrets(self):
        from daily_metric_integrity import emit_integrity_audit, validate_app_metrics

        row = valid_row()
        row["api_key"] = "sanitized-secret-key"
        row["provenance"] = {
            "mrr_total": MetricProvenance(
                endpoint_class="analytics",
                metric_id="mrr",
                series_key="data.revenue",
                date_from="2026-08-05",
                date_to="2026-08-06",
                expected_date="2026-08-06",
            )
        }
        validated = validate_app_metrics(row)

        with self.assertLogs("daily_metric_integrity", level="INFO") as captured:
            emit_integrity_audit(
                report_date=date(2026, 8, 6),
                timezone="Europe/Minsk",
                rows=(validated,),
                total_status={
                    "mrr_total": True,
                    "revenue_total": False,
                    "conversion": False,
                },
                portfolio_issues=(),
            )

        output = "\n".join(captured.output)
        self.assertIn("report_date=2026-08-06", output)
        self.assertIn("slot=1", output)
        self.assertIn("app=Unfollowers: Follow & Unfollow", output)
        self.assertIn("metric=mrr_total status=valid", output)
        self.assertIn("endpoint=analytics", output)
        self.assertIn("source=mrr:data.revenue", output)
        self.assertIn("date_from=2026-08-05 date_to=2026-08-06", output)
        self.assertIn("expected_date=2026-08-06 portfolio=daily-v1", output)
        self.assertIn("request_status=attempted", output)
        self.assertIn("total_metric=revenue_total status=invalid", output)
        self.assertIn(
            "total_metric=conversion status=invalid endpoint=derived "
            "source=canonical_raw_count_ratio",
            output,
        )
        self.assertNotIn("sanitized-secret-key", output)
        self.assertNotIn("api_key", output)


if __name__ == "__main__":
    unittest.main()
