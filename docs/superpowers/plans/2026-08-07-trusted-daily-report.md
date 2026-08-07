# Trusted Adapty Daily Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish only canonical, source-validated Adapty metrics in the main Telegram report, quarantine each untrusted metric as `N/A`, and make every displayed Total exactly reproducible from the three displayed applications.

**Architecture:** A new `daily_report_contract.py` module owns the immutable three-slot portfolio and secret-safe configuration issues. A new `daily_metric_integrity.py` module owns pure per-field validation, reconciliation, quarantine, trust markers, and audit logging. `adapty_client.py` collects a typed daily snapshot, while `report_builder.py` formats only validated values and recomputes fail-closed totals.

**Tech Stack:** Python 3.11+, `dataclasses`, `requests`, `concurrent.futures`, standard-library `logging`, `unittest.mock`, Railway CLI, Adapty Export API.

## Global Constraints

- The daily report portfolio is exactly `Unfollowers: Follow & Unfollow`, `Granny Photos`, and `Otty: Couples&Relationships`, in that order.
- Every main-report request and boundary uses `Europe/Minsk`.
- MRR, ARR, and Revenue use only Adapty gross `data.revenue`; never use `proceeds` or `net_revenue` as a fallback.
- Invalid values become `N/A`; zero remains valid.
- A portfolio total is numeric only when all three canonical application fields needed by that total are trusted.
- Total conversion is `sum(value_to) / sum(value_from) * 100` and never an average of displayed percentages.
- APP4+, visibility overrides, raw responses, API keys, authorization headers, Telegram tokens, and Railway secrets never enter calculations or logs.
- A/B and Apple Ads metric definitions and delivery behavior remain unchanged.
- Use `python -m unittest discover -s tests -v`; `pytest` is not a dependency.
- Follow `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before merge or deployment.

---

### Task 1: Add the immutable daily portfolio contract

**Files:**
- Create: `daily_report_contract.py`
- Create: `tests/test_daily_report_contract.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: environment mappings containing `ADAPTY_API_KEY_APP{N}`, `ADAPTY_APP_NAME_{N}`, and optional visibility variables.
- Produces: `IntegrityIssue`, `DailyAppSlot`, `DailyPortfolio`, `CANONICAL_APP_NAMES`, and `load_daily_portfolio(environ: Optional[Mapping[str, str]] = None) -> DailyPortfolio`.

- [ ] **Step 1: Write failing contract tests**

Create tests using sanitized keys:

```python
class TestDailyPortfolioContract(unittest.TestCase):
    def test_loads_exact_three_canonical_slots_and_hides_keys_from_repr(self):
        from daily_report_contract import CANONICAL_APP_NAMES, load_daily_portfolio

        env = {
            "ADAPTY_API_KEY_APP1": "secret-one",
            "ADAPTY_APP_NAME_1": CANONICAL_APP_NAMES[0],
            "ADAPTY_API_KEY_APP2": "secret-two",
            "ADAPTY_APP_NAME_2": CANONICAL_APP_NAMES[1],
            "ADAPTY_API_KEY_APP3": "secret-three",
            "ADAPTY_APP_NAME_3": CANONICAL_APP_NAMES[2],
        }
        portfolio = load_daily_portfolio(env)

        self.assertEqual(tuple(slot.name for slot in portfolio.slots), CANONICAL_APP_NAMES)
        self.assertEqual(portfolio.issues, ())
        self.assertNotIn("secret-one", repr(portfolio))

    def test_wrong_or_missing_slot_is_not_fetchable(self):
        from daily_report_contract import load_daily_portfolio

        portfolio = load_daily_portfolio({
            "ADAPTY_API_KEY_APP1": "key-one",
            "ADAPTY_APP_NAME_1": "Wrong App",
        })

        self.assertIsNone(portfolio.slots[0].api_key)
        self.assertIsNone(portfolio.slots[1].api_key)
        self.assertIsNone(portfolio.slots[2].api_key)
        self.assertIn("config.wrong_name", {issue.code for issue in portfolio.issues})
        self.assertIn("config.missing_key", {issue.code for issue in portfolio.issues})

    def test_extra_slots_and_visibility_are_ignored_and_flagged(self):
        from daily_report_contract import CANONICAL_APP_NAMES, load_daily_portfolio

        env = {
            **{
                f"ADAPTY_API_KEY_APP{i}": f"key-{i}"
                for i in range(1, 5)
            },
            **{
                f"ADAPTY_APP_NAME_{i}": name
                for i, name in enumerate(CANONICAL_APP_NAMES, start=1)
            },
            "ADAPTY_APP_NAME_4": "TeaNote",
            "ADAPTY_APP_VISIBLE_3": "false",
        }
        portfolio = load_daily_portfolio(env)

        self.assertEqual(len(portfolio.slots), 3)
        self.assertTrue(all(slot.is_visible for slot in portfolio.slots))
        self.assertEqual(
            {issue.code for issue in portfolio.issues},
            {"config.extra_slot", "config.visibility_override"},
        )
```

- [ ] **Step 2: Run the new tests and observe RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_daily_report_contract -v
```

Expected: `ModuleNotFoundError: No module named 'daily_report_contract'`.

- [ ] **Step 3: Implement the contract types and loader**

Create:

```python
from dataclasses import dataclass, field
import os
import re
from typing import Mapping, Optional

CANONICAL_APP_NAMES = (
    "Unfollowers: Follow & Unfollow",
    "Granny Photos",
    "Otty: Couples&Relationships",
)


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    message: str
    app_name: Optional[str] = None
    metric: Optional[str] = None


@dataclass(frozen=True)
class DailyAppSlot:
    index: int
    name: str
    api_key: Optional[str] = field(default=None, repr=False)
    is_visible: bool = True


@dataclass(frozen=True)
class DailyPortfolio:
    slots: tuple[DailyAppSlot, ...]
    issues: tuple[IntegrityIssue, ...]


def load_daily_portfolio(
    environ: Optional[Mapping[str, str]] = None,
) -> DailyPortfolio:
    source = os.environ if environ is None else environ
    slots: list[DailyAppSlot] = []
    issues: list[IntegrityIssue] = []
    for index, expected_name in enumerate(CANONICAL_APP_NAMES, start=1):
        key = source.get(f"ADAPTY_API_KEY_APP{index}", "").strip()
        actual_name = source.get(f"ADAPTY_APP_NAME_{index}", "").strip()
        fetchable_key: Optional[str] = key or None
        if actual_name != expected_name:
            fetchable_key = None
            issues.append(IntegrityIssue(
                code="config.wrong_name",
                message=f"APP{index}: expected '{expected_name}', got '{actual_name or 'empty'}'",
                app_name=expected_name,
            ))
        if not key:
            issues.append(IntegrityIssue(
                code="config.missing_key",
                message=f"APP{index}: Secret API key is missing",
                app_name=expected_name,
            ))
        slots.append(DailyAppSlot(index=index - 1, name=expected_name, api_key=fetchable_key))

    if any(re.fullmatch(r"ADAPTY_(?:API_KEY_APP|APP_NAME_)(?:[4-9]|[1-9][0-9]+)", key) for key in source):
        issues.append(IntegrityIssue(
            code="config.extra_slot",
            message="APP4+ variables are ignored by the daily report",
        ))
    if any(re.fullmatch(r"ADAPTY_APP_VISIBLE_[1-9][0-9]*", key) for key in source):
        issues.append(IntegrityIssue(
            code="config.visibility_override",
            message="visibility overrides are ignored by the daily report",
        ))
    return DailyPortfolio(slots=tuple(slots), issues=tuple(issues))
```

- [ ] **Step 4: Document the strict contract in `.env.example`**

State that APP1–APP3 names are exact, visibility overrides are unsupported for the main report, and APP4+ is rejected as stale configuration. Do not add any key values.

- [ ] **Step 5: Run focused and existing config tests**

```bash
.venv/bin/python -m unittest tests.test_daily_report_contract tests.test_config -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add daily_report_contract.py tests/test_daily_report_contract.py .env.example
git commit -m "feat: enforce canonical daily report portfolio"
```

---

### Task 2: Add pure per-metric validation and quarantine

**Files:**
- Create: `daily_metric_integrity.py`
- Create: `tests/test_daily_metric_integrity.py`

**Interfaces:**
- Consumes: application row dictionaries with keys `mrr_total`, `mrr_delta_24h`, `arr_total`, `arr_delta_24h`, `revenue_total`, `revenue_per_day`, `installs_total`, `installs_delta_24h`, `conv_rate`, `conv_from`, `conv_to`, and optional `issues`.
- Produces: `validate_app_metrics(row: dict[str, Any]) -> dict[str, Any]`, `count_integrity_problems(rows: Sequence[dict[str, Any]], portfolio_issues: Sequence[IntegrityIssue]) -> int`, and `emit_integrity_audit(report_date: date, timezone: str, rows: Sequence[dict[str, Any]], total_status: Mapping[str, bool], portfolio_issues: Sequence[IntegrityIssue]) -> None`.

- [ ] **Step 1: Write failing numeric and within-metric tests**

Use this helper returning one completely valid row:

```python
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
```

Then add:

```python
def test_revenue_inconsistency_quarantines_only_revenue_family(self):
    from daily_metric_integrity import validate_app_metrics

    row = valid_row()
    row["revenue_total"] = 10.0
    row["revenue_per_day"] = 11.0
    result = validate_app_metrics(row)

    self.assertIsNone(result["revenue_total"])
    self.assertIsNone(result["revenue_per_day"])
    self.assertEqual(result["mrr_total"], row["mrr_total"])
    self.assertIn("revenue.day_exceeds_mtd", {i.code for i in result["issues"]})

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
```

Add these exact cases to the same test class:

```python
def test_invalid_numeric_types_are_quarantined(self):
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
    row = valid_row()
    row.update(conv_rate=0.0, conv_from=0, conv_to=0)
    self.assertEqual(validate_app_metrics(row)["conv_rate"], 0.0)

    row.update(conv_rate=1.0, conv_from=0, conv_to=0)
    self.assertIsNone(validate_app_metrics(row)["conv_rate"])

def test_paid_count_cannot_exceed_eligible_count(self):
    row = valid_row()
    row.update(conv_rate=100.0, conv_from=5, conv_to=6)
    result = validate_app_metrics(row)
    self.assertIsNone(result["conv_from"])
    self.assertIn("conversion.invalid_counts", {i.code for i in result["issues"]})
```

- [ ] **Step 2: Run and observe RED**

```bash
.venv/bin/python -m unittest tests.test_daily_metric_integrity -v
```

Expected: module import failure.

- [ ] **Step 3: Implement field validation and family quarantine**

Implement these constants and helpers:

```python
MONETARY_FIELDS = (
    "mrr_total", "arr_total", "revenue_total", "revenue_per_day",
)
DELTA_FIELDS = ("mrr_delta_24h", "arr_delta_24h")
COUNT_FIELDS = (
    "installs_total", "installs_delta_24h", "conv_from", "conv_to",
)
REPORT_VALUE_FIELDS = (
    "mrr_total", "mrr_delta_24h", "arr_total", "arr_delta_24h",
    "revenue_total", "revenue_per_day", "installs_total",
    "installs_delta_24h", "conv_rate", "conv_from", "conv_to",
)


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _quarantine(
    result: dict[str, Any],
    keys: tuple[str, ...],
    issue: IntegrityIssue,
) -> None:
    for key in keys:
        result[key] = None
    issues = list(result.get("issues", ()))
    if issue.code not in {existing.code for existing in issues}:
        issues.append(issue)
    result["issues"] = tuple(issues)
```

`validate_app_metrics` must return a copy without mutating its input and apply these operations in order:

1. quarantine any non-finite `MONETARY_FIELDS` value or any negative value;
2. quarantine any non-finite `DELTA_FIELDS` value while allowing negative deltas;
3. quarantine any `COUNT_FIELDS` value that is boolean, negative, non-finite, or non-integral;
4. quarantine both Revenue fields when report-day Revenue exceeds Revenue MTD;
5. quarantine both Installs fields when report-day Installs exceeds Installs MTD;
6. quarantine all conversion fields when counts are inconsistent or the returned percentage differs from the count-derived percentage by more than `0.01` percentage point;
7. quarantine `arr_total` when it differs from `mrr_total * 12` by more than `$0.05` and independently quarantine `arr_delta_24h` when it differs from `mrr_delta_24h * 12` by more than `$0.05`.

Every quarantine operation adds exactly one `IntegrityIssue` whose `app_name` comes from `row["name"]` and whose `metric` is the affected public field or family.

- [ ] **Step 4: Write failing ARR reconciliation tests**

```python
def test_arr_value_mismatch_quarantines_arr_but_preserves_mrr(self):
    from daily_metric_integrity import validate_app_metrics

    row = valid_row()
    row["mrr_total"] = 100.0
    row["arr_total"] = 1199.90
    result = validate_app_metrics(row)

    self.assertEqual(result["mrr_total"], 100.0)
    self.assertIsNone(result["arr_total"])
    self.assertIn("arr.mrr_multiple_mismatch", {i.code for i in result["issues"]})

def test_arr_tolerance_accepts_rounding_noise(self):
    from daily_metric_integrity import validate_app_metrics

    row = valid_row()
    row["mrr_total"] = 100.0
    row["arr_total"] = 1200.04
    self.assertEqual(validate_app_metrics(row)["arr_total"], 1200.04)
```

Run to observe the mismatch test fail, then implement `$0.05` current-value and delta tolerances independently.

- [ ] **Step 5: Add audit and problem-count tests**

Assert `count_integrity_problems` counts unique row issues plus portfolio issues. With `assertLogs`, verify `emit_integrity_audit` logs report date, slot, app, field status, and issue code but does not contain a supplied sanitized key or any row field named `api_key`.

Deduplicate issue identities exactly as:

```python
identity = (issue.code, issue.app_name, issue.metric)
```

Call the audit function in the test with:

```python
emit_integrity_audit(
    report_date=date(2026, 8, 6),
    timezone="Europe/Minsk",
    rows=(validate_app_metrics(valid_row()),),
    total_status={"mrr_total": True, "revenue_total": False},
    portfolio_issues=(),
)
```

Implement row audit events with fixed fields and no metric values:

```python
for row in rows:
    issue_by_metric = {
        issue.metric: issue.code for issue in row.get("issues", ())
    }
    for metric in REPORT_VALUE_FIELDS:
        logger.info(
            "daily_metric_audit report_date=%s timezone=%s slot=%s app=%s metric=%s status=%s issue=%s",
            report_date.isoformat(),
            timezone,
            int(row["index"]) + 1,
            row["name"],
            metric,
            "valid" if row.get(metric) is not None else "invalid",
            issue_by_metric.get(metric, "none"),
        )
```

- [ ] **Step 6: Run focused tests and commit**

```bash
.venv/bin/python -m unittest tests.test_daily_metric_integrity -v
git add daily_metric_integrity.py tests/test_daily_metric_integrity.py
git commit -m "feat: quarantine inconsistent daily metrics"
```

---

### Task 3: Collect a typed canonical daily snapshot

**Files:**
- Modify: `adapty_client.py`
- Modify: `tests/test_adapty_client.py`

**Interfaces:**
- Consumes: `DailyPortfolio` from `load_daily_portfolio()` and `validate_app_metrics`.
- Produces: `DailyMetricsSnapshot` and `fetch_daily_snapshot(report_date: Union[date, datetime, None] = None) -> DailyMetricsSnapshot`; preserves `fetch_all_metrics(...) -> list[dict[str, Any]]` as a compatibility wrapper.

- [ ] **Step 1: Add `DailyMetricsSnapshot` to the contract module through a failing import test**

Expected type:

```python
@dataclass(frozen=True)
class DailyMetricsSnapshot:
    rows: tuple[dict[str, Any], ...]
    portfolio_issues: tuple[IntegrityIssue, ...]
```

Update the contract module import to `from typing import Any, Mapping, Optional` before adding this type.

Add this import assertion to `tests/test_daily_report_contract.py`, observe failure, implement it, and rerun that focused module:

```python
def test_daily_metrics_snapshot_preserves_rows_and_portfolio_issues(self):
    from daily_report_contract import DailyMetricsSnapshot, IntegrityIssue

    issue = IntegrityIssue(code="config.extra_slot", message="APP4 ignored")
    snapshot = DailyMetricsSnapshot(rows=({"name": "App"},), portfolio_issues=(issue,))
    self.assertEqual(snapshot.rows[0]["name"], "App")
    self.assertEqual(snapshot.portfolio_issues, (issue,))
```

- [ ] **Step 2: Write failing canonical collection tests**

Patch `load_daily_portfolio` with three sanitized slots and `_fetch_app_snapshot` with ordered results. Assert `fetch_daily_snapshot(date(2026, 8, 6))` returns exactly three rows in canonical order and calls `validate_app_metrics` for every fetched row.

Add a missing-key case:

```python
self.assertEqual(snapshot.rows[2]["name"], "Otty: Couples&Relationships")
self.assertTrue(all(snapshot.rows[2][key] is None for key in REPORT_VALUE_KEYS))
self.assertIn("config.missing_key", {i.code for i in snapshot.rows[2]["issues"]})
```

Assert an extra APP4 slot cannot be submitted to the executor because the loader never returns it.

- [ ] **Step 3: Run the focused tests and observe RED**

```bash
.venv/bin/python -m unittest tests.test_adapty_client.TestFetchDailySnapshot -v
```

Expected: `ImportError` for `fetch_daily_snapshot`.

- [ ] **Step 4: Implement canonical collection**

Extract a `_missing_app_row(slot: DailyAppSlot, issues: Sequence[IntegrityIssue]) -> dict[str, Any]` helper that returns every report value key as `None`, `is_visible=True`, and only issues relevant to that slot.

Rename the current collection implementation to `fetch_daily_snapshot`, use `load_daily_portfolio`, skip executor submission for slots with `api_key is None`, validate all fetched and missing rows, sort by `index`, and return `DailyMetricsSnapshot`.

Keep:

```python
def fetch_all_metrics(
    report_date: Union[date, datetime, None] = None,
) -> list[dict[str, Any]]:
    return list(fetch_daily_snapshot(report_date).rows)
```

- [ ] **Step 5: Preserve existing request/date/backfill coverage**

Run all client tests. Update only mocks that now target `load_daily_portfolio`; do not weaken assertions for gross series, five requests, pacing, exact dates, raw counts, stale points, or Aug 6 backfill.

- [ ] **Step 6: Commit**

```bash
.venv/bin/python -m unittest tests.test_daily_report_contract tests.test_daily_metric_integrity tests.test_adapty_client -v
git add daily_report_contract.py adapty_client.py tests/test_daily_report_contract.py tests/test_adapty_client.py
git commit -m "feat: collect canonical validated daily snapshots"
```

---

### Task 4: Render per-metric trust status and fail-closed totals

**Files:**
- Modify: `report_builder.py`
- Modify: `tests/test_report_builder.py`

**Interfaces:**
- Consumes: `fetch_daily_snapshot`, validated row values, row `issues`, and `portfolio_issues`.
- Produces: `ReportBuildResult(text, report_date, anomalies, integrity_problem_count)` and existing `build_report` / `build_report_text` entry points.

- [ ] **Step 1: Convert report fixtures to three canonical rows**

Replace two generic rows with three rows named from `CANONICAL_APP_NAMES` and complete valid metrics whose totals are easy to calculate. Include `issues=()` on each row and return exactly:

```python
def valid_rows() -> list[dict]:
    rows: list[dict] = []
    for index, name in enumerate(CANONICAL_APP_NAMES, start=1):
        mrr = float(index * 100)
        conv_from = 100 * index
        conv_to = index
        rows.append({
            "index": index - 1,
            "name": name,
            "mrr_total": mrr,
            "mrr_delta_24h": float(index),
            "arr_total": mrr * 12,
            "arr_delta_24h": float(index * 12),
            "revenue_total": float(index * 100),
            "revenue_per_day": float(index * 10),
            "installs_total": 1000 * index,
            "installs_delta_24h": 100 * index,
            "conv_rate": conv_to / conv_from * 100,
            "conv_from": conv_from,
            "conv_to": conv_to,
            "issues": (),
            "is_visible": True,
        })
    return rows


def build_with_rows(
    rows: list[dict],
    portfolio_issues: tuple[IntegrityIssue, ...] = (),
):
    snapshot = DailyMetricsSnapshot(
        rows=tuple(rows),
        portfolio_issues=portfolio_issues,
    )
    with patch("report_builder.fetch_daily_snapshot", return_value=snapshot):
        return build_report(date(2026, 8, 6))
```

This prevents tests from accidentally proving totals over a non-production app set.

- [ ] **Step 2: Write failing trust-marker tests**

```python
def test_complete_report_shows_passed_integrity_marker(self):
    result = build_with_rows(valid_rows())
    self.assertIn("✅ Проверка данных: пройдена", result.text)
    self.assertEqual(result.integrity_problem_count, 0)

def test_partial_report_shows_problem_count_and_na(self):
    rows = valid_rows()
    rows[2]["revenue_total"] = None
    rows[2]["issues"] = (IntegrityIssue(
        code="revenue.invalid",
        message="Revenue response is invalid",
        app_name=CANONICAL_APP_NAMES[2],
        metric="revenue_total",
    ),)
    result = build_with_rows(rows)
    self.assertIn("Otty: Couples&amp;Relationships", result.text)
    self.assertIn("Revenue (месяц): $N/A", result.text)
    self.assertIn("Total Revenue (месяц): $N/A", result.text)
    self.assertIn("⚠️ Проверка данных: обнаружено 1 проблем", result.text)
    self.assertIn("Total MRR", result.text)
```

Run and observe failure because the current builder has no trust marker or problem count.

- [ ] **Step 3: Update `ReportBuildResult` and snapshot consumption**

Add:

```python
@dataclass
class ReportBuildResult:
    text: str
    report_date: date
    anomalies: list[str]
    integrity_problem_count: int = 0
```

Import and call `fetch_daily_snapshot`. Combine `portfolio_issues` and every row's `issues` into escaped anomaly details. Use `count_integrity_problems` for the footer and result field.

- [ ] **Step 4: Make value/delta display atomic where required**

Write these failing tests using the three-row valid snapshot fixture:

```python
def test_missing_mrr_value_quarantines_current_total(self):
    rows = valid_rows()
    rows[2]["mrr_total"] = None
    text = build_with_rows(rows).text
    self.assertIn("MRR (на дату): $N/A", text)
    self.assertIn("Total MRR (на дату): $N/A", text)

def test_missing_mrr_delta_preserves_current_value_only(self):
    rows = valid_rows()
    rows[2]["mrr_delta_24h"] = None
    text = build_with_rows(rows).text
    self.assertIn("MRR (на дату): $300 (⚠️ N/A)", text)
    self.assertIn("Total MRR (на дату): $600 (⚠️ N/A)", text)

def test_missing_revenue_mtd_preserves_trusted_daily_revenue(self):
    rows = valid_rows()
    rows[2]["revenue_total"] = None
    text = build_with_rows(rows).text
    self.assertIn("Revenue (месяц): $N/A (+$30)", text)
    self.assertIn("Total Revenue (месяц): $N/A (+$60)", text)

def test_missing_conversion_counts_make_total_conversion_na(self):
    rows = valid_rows()
    rows[2].update(conv_rate=None, conv_from=None, conv_to=None)
    self.assertIn("Total Conv. (месяц): N/A", build_with_rows(rows).text)

def test_portfolio_only_issue_preserves_values_but_warns(self):
    issue = IntegrityIssue(code="config.extra_slot", message="APP4 ignored")
    result = build_with_rows(valid_rows(), portfolio_issues=(issue,))
    self.assertIn("Total MRR (на дату): $600", result.text)
    self.assertIn("⚠️ Проверка данных: обнаружено 1 проблем", result.text)
```

Implement only the formatting changes needed for these assertions.

- [ ] **Step 5: Emit secret-free audit events**

Call `emit_integrity_audit` after totals are resolved and before returning `ReportBuildResult`. Add an `assertLogs` test that verifies canonical app names and status codes appear while sanitized key strings do not.

```python
emit_integrity_audit(
    report_date=resolved_report_date,
    timezone=snapshot_tz,
    rows=rows,
    total_status={
        "mrr_total": total_mrr is not None,
        "mrr_delta_24h": total_mrr_delta is not None,
        "arr_total": total_arr is not None,
        "arr_delta_24h": total_arr_delta is not None,
        "revenue_total": total_revenue is not None,
        "revenue_per_day": total_revenue_per_day is not None,
        "installs_delta_24h": total_inst_delta is not None,
        "conversion": total_conv is not None,
    },
    portfolio_issues=snapshot.portfolio_issues,
)
```

- [ ] **Step 6: Run focused and full tests, then commit**

```bash
.venv/bin/python -m unittest tests.test_report_builder -v
.venv/bin/python -m unittest discover -s tests -v
git add report_builder.py tests/test_report_builder.py
git commit -m "feat: expose trusted per-metric report status"
```

---

### Task 5: Keep every delivery path consistent

**Files:**
- Modify: `scheduler.py`
- Modify: `telegram_sender.py`
- Modify: `telegram_bot.py`
- Modify: `tests/test_scheduler.py`
- Modify: `tests/test_telegram_sender.py`
- Create: `tests/test_telegram_bot_daily_report.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `ReportBuildResult.integrity_problem_count` and `ReportBuildResult.anomalies`.
- Produces: identical partial-report behavior for scheduled delivery, `--test-send`, and manual Collect Data.

- [ ] **Step 1: Update all `ReportBuildResult` test fixtures**

Set `integrity_problem_count=0` for clean reports and a positive value for anomaly cases.

- [ ] **Step 2: Write failing scheduled-delivery tests**

Assert a partial main report is sent exactly once, follow-up A/B and Apple Ads reports are still attempted, and an admin alert includes the same non-secret issue details. Assert the clean path sends no admin alert.

Use this partial result and core assertions in `tests/test_scheduler.py`:

```python
mock_build_report.return_value = ReportBuildResult(
    text="Partial main report",
    report_date=date(2026, 8, 6),
    anomalies=["Otty: Revenue response is invalid"],
    integrity_problem_count=1,
)

_send_daily_job()

self.assertEqual(mock_send.call_args_list[0].args[0], "Partial main report")
self.assertIn("AB report", [call.args[0] for call in mock_send.call_args_list])
self.assertIn("Apple Ads report", [call.args[0] for call in mock_send.call_args_list])
admin_calls = [call for call in mock_send.call_args_list if call.kwargs.get("chat_id") == "42"]
self.assertEqual(len(admin_calls), 1)
self.assertIn("Otty: Revenue response is invalid", admin_calls[0].args[0])
```

- [ ] **Step 3: Write failing test-send and manual collection tests**

For `telegram_sender.test_send`, assert the partial report text is sent unchanged and follow-ups remain independent.

For `telegram_bot._collect_and_send`, assert its user response says `Проблем проверки данных: 2`, and the admin receives details when configured. Patch network delivery only; use a real `ReportBuildResult`.

```python
mock_build_report.return_value = ReportBuildResult(
    text="Partial main report",
    report_date=date(2026, 8, 6),
    anomalies=["Otty: Revenue invalid", "Granny Photos: Conversion invalid"],
    integrity_problem_count=2,
)

ok, message = _collect_and_send(chat_id="42", to_group=True)

self.assertTrue(ok)
self.assertIn("Проблем проверки данных: 2", message)
self.assertEqual(mock_send.call_args_list[0].args[0], "Partial main report")
```

- [ ] **Step 4: Implement consistent wording**

Use `integrity_problem_count` rather than `bool(anomalies)` for user-facing status. Keep the main report delivery policy selected by the user: partial reports are sent, invalid metrics are `N/A`, and independent follow-ups continue.

Do not add raw exception text or credentials to Telegram alerts.

Use this exact suffix rule in manual collection:

```python
if report.integrity_problem_count:
    msg += f" ⚠️ Проблем проверки данных: {report.integrity_problem_count}."
```

- [ ] **Step 5: Document the trust contract**

In `README.md`, document the exact three apps, per-metric `N/A`, fail-closed totals, trust footer, backfill semantics, and audit logs. State that a numeric report is a validated timestamped snapshot, not an immutable historical ledger.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/python -m unittest tests.test_scheduler tests.test_telegram_sender tests.test_telegram_bot_daily_report -v
.venv/bin/python -m unittest discover -s tests -v
git add scheduler.py telegram_sender.py telegram_bot.py README.md tests/test_scheduler.py tests/test_telegram_sender.py tests/test_telegram_bot_daily_report.py
git commit -m "feat: deliver integrity-aware daily reports"
```

---

### Task 6: Review, configure Otty, reconcile, and deploy

**Files:**
- Modify: Railway production variables only after explicit action-time confirmation
- Merge reviewed implementation commits to `main`
- Push tested `main` to `origin`

**Interfaces:**
- Consumes: the linked Railway project `Adapty Stats TG Bot`, environment `production`, service `worker`, and the signed-in Adapty browser session.
- Produces: a successful Railway deployment and no-send parity evidence for the canonical portfolio.

- [ ] **Step 1: Run implementation review**

Read and follow `superpowers:requesting-code-review`. Require no unresolved Critical or Important findings for:

- canonical scope enforcement;
- per-metric quarantine;
- source/date/numeric/reconciliation rules;
- secret-safe audit output;
- delivery behavior;
- unchanged A/B and Apple Ads definitions.

- [ ] **Step 2: Run completion verification in the feature worktree**

```bash
.venv/bin/python -m compileall -q .
.venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short
```

Require all commands to pass and a clean committed worktree.

- [ ] **Step 3: Obtain action-time approval and transfer Otty key safely**

Ask exactly for permission to open Otty's Secret API key in Adapty and write it to Railway production. After approval, use the Adapty Copy control and a non-echoing stdin path such as `pbpaste | railway variable set ADAPTY_API_KEY_APP3 --stdin --skip-deploys`; never put the value in a command argument or output.

Set the exact APP1–APP3 names, delete APP4 key/name and all visibility overrides, and preserve Telegram, A/B, Apple Ads, and schedule variables.

- [ ] **Step 4: Run no-send production previews**

Using Railway variables, build report text for 6 August and the latest closed `Europe/Minsk` day without calling Telegram functions. Require exactly three canonical rows, no unexplained integrity issues, and trust marker `passed` or explicit `N/A` quarantine.

- [ ] **Step 5: Reconcile with Adapty Dashboard**

For the same snapshot, compare each app and Total for MRR current/delta, ARR current/delta, Revenue MTD/day, Installs MTD/day, and conversion percentage/raw counts. Use `GMT+3`, the same dates, gross Revenue, and new `device_id` installs.

Backfill is acceptable only when current Export API and current Dashboard agree. Any same-snapshot difference blocks deployment.

- [ ] **Step 6: Integrate and push**

Read and follow `superpowers:finishing-a-development-branch`. Under the user's standing authorization to choose, merge locally into `main`, rerun the complete suite on merged `main`, and push only the verified commit.

- [ ] **Step 7: Verify Railway terminal success and runtime logs**

Wait for the `worker` deployment of the exact pushed commit to reach `SUCCESS`. Inspect startup and integrity audit logs for errors and secret leakage. Run one final no-send production preview and do not send an extra Telegram message.

- [ ] **Step 8: Record handoff evidence**

Report the final commit, test count, deployment ID/status, exact canonical names, no-send preview result, same-snapshot reconciliation result, any explained Adapty backfill, and confirmation that no secret or extra Telegram message was exposed.

## Done When

- APP4+, hidden rows, wrong names, and wrong keys cannot contribute to the main report.
- Every numeric field has passed source, date, numeric, and reconciliation checks.
- Each invalid metric and dependent total renders `N/A` without suppressing unrelated trusted values.
- The Telegram footer states whether integrity passed or how many problems were found.
- Audit logs explain every metric status without secrets.
- All tests pass before and after integration.
- Railway production runs the exact tested commit and the three-app no-send preview reconciles with Adapty.
