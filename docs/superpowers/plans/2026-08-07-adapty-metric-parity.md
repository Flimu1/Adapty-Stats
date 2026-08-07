# Adapty Metric Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task by task.

**Goal:** Make the Telegram report reconcile with Adapty for the explicit Unfollowers, Granny Photos, and Otty portfolio while preserving raw conversion counts, preventing partial totals, and reducing each application to five internally consistent API responses.

**Architecture:** `adapty_client.py` will parse each Adapty response into typed summary-and-series results, then build one application snapshot from two daily-series requests, two month-to-date series requests, and one conversion request. `report_builder.py` will filter visible rows first and calculate every total from only those displayed rows, failing closed per metric when any required value is missing. Railway will contain three contiguous application slots matching the canonical portfolio.

**Tech Stack:** Python 3, `requests`, `dataclasses`, `concurrent.futures`, `unittest.mock`, Railway CLI, Adapty Export API.

## Global Constraints

- Follow `superpowers:test-driven-development`: add one failing behavior test, observe the expected failure, implement the smallest production change, and observe the test pass before continuing.
- Work in an isolated `codex/adapty-metric-parity` worktree created through `superpowers:using-git-worktrees`.
- Keep all reporting date boundaries and the `Adapty-Tz` request header on `Europe/Minsk`.
- Use only Adapty's gross `revenue` series for MRR, ARR, and Revenue. Never fall back to `proceeds` or `net_revenue`.
- Never print, log, commit, or place an Adapty Secret API key in a shell argument captured in output.
- Do not change the A/B report or Apple Ads report paths.
- Run `python -m unittest discover -s tests -v`; `pytest` is not a project dependency.

---

## Task 1: Parse complete Adapty chart and conversion responses

**Files:**

- Create: `tests/test_adapty_client.py`
- Modify: `adapty_client.py`

### Step 1: Write failing chart-parser tests

Create representative sanitized response fixtures matching the observed Export API structure:

```python
MRR_RESPONSE = {
    "data": {
        "revenue": {
            "value": 1272.866100428855,
            "data": [{
                "values": [
                    {"x": "2026-08-05", "y": 1380.73},
                    {"x": "2026-08-06", "y": 1272.866100428855},
                ]
            }],
        },
        "proceeds": {"value": 890.0, "data": [{"values": []}]},
    }
}

INSTALLS_RESPONSE = {
    "data": {
        "common": {
            "value": 1793,
            "data": [{
                "values": [
                    {"x": "2026-08-01", "y": 300},
                    {"x": "2026-08-06", "y": 321},
                ]
            }],
        }
    }
}
```

Add tests for `_parse_chart_metric` asserting:

```python
metric = _parse_chart_metric(MRR_RESPONSE, "mrr")
self.assertEqual(metric.value, 1272.866100428855)
self.assertEqual(metric.daily_values, (1380.73, 1272.866100428855))

metric = _parse_chart_metric(INSTALLS_RESPONSE, "installs")
self.assertEqual(metric.value, 1793.0)
self.assertEqual(metric.daily_values, (300.0, 321.0))
```

Also assert that an MRR payload containing only `proceeds` returns `None`, because a net-value fallback cannot reconcile with the gross Dashboard card.

### Step 2: Run the focused test and observe RED

Run:

```bash
.venv/bin/python -m unittest tests.test_adapty_client -v
```

Expected failure: `ImportError` for `_parse_chart_metric` or failed assertions because the current parser discards daily values and accepts `proceeds`.

### Step 3: Implement typed chart parsing

Add this result type near the imports in `adapty_client.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ChartMetric:
    value: float
    daily_values: tuple[float, ...]
```

Implement pure helpers with these signatures:

```python
def _metric_key(chart_id: str) -> str:
    if chart_id in {"mrr", "arr", "revenue"}:
        return "revenue"
    if chart_id == "installs":
        return "common"
    raise ValueError(f"Unsupported Adapty chart: {chart_id}")


def _parse_chart_metric(payload: dict[str, Any], chart_id: str) -> Optional[ChartMetric]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    metric = data.get(_metric_key(chart_id))
    if not isinstance(metric, dict):
        return None
    try:
        value = float(metric["value"])
    except (KeyError, TypeError, ValueError):
        return None
    daily_values: list[float] = []
    series = metric.get("data")
    if isinstance(series, list) and series and isinstance(series[0], dict):
        values = series[0].get("values")
        if isinstance(values, list):
            for point in values:
                try:
                    daily_values.append(float(point["y"]))
                except (KeyError, TypeError, ValueError):
                    return None
    return ChartMetric(value=value, daily_values=tuple(daily_values))
```

Change `_fetch_chart` to return `Optional[ChartMetric]` and delegate response parsing to `_parse_chart_metric`.

### Step 4: Add conversion parser tests and observe RED

Add this fixture and assertion:

```python
CONVERSION_RESPONSE = {
    "value": 0.8365867261572784,
    "value_from": 1793,
    "value_to": 15,
    "metric_name": "install_paid",
    "data": [],
}

metric = _parse_conversion_metric(CONVERSION_RESPONSE)
self.assertEqual(metric.value, 0.8365867261572784)
self.assertEqual(metric.value_from, 1793)
self.assertEqual(metric.value_to, 15)
```

Add failure cases for a missing raw count, a negative raw count, and a response whose `metric_name` is not `install_paid`; each must return `None`.

Run the focused test and confirm it fails because raw counts are currently discarded.

### Step 5: Implement typed conversion parsing

Add:

```python
@dataclass(frozen=True)
class ConversionMetric:
    value: float
    value_from: int
    value_to: int
```

Implement:

```python
def _parse_conversion_metric(payload: dict[str, Any]) -> Optional[ConversionMetric]:
    if payload.get("metric_name") != "install_paid":
        return None
    try:
        value = float(payload["value"])
        value_from = int(payload["value_from"])
        value_to = int(payload["value_to"])
    except (KeyError, TypeError, ValueError):
        return None
    if value_from < 0 or value_to < 0 or value_to > value_from:
        return None
    return ConversionMetric(value=value, value_from=value_from, value_to=value_to)
```

Change `_fetch_conversion` to return `Optional[ConversionMetric]` and use this parser. Do not multiply values between zero and one by 100: the observed API `value` is already expressed as a percentage.

### Step 6: Verify and commit

Run:

```bash
.venv/bin/python -m unittest tests.test_adapty_client -v
```

Commit:

```bash
git add adapty_client.py tests/test_adapty_client.py
git commit -m "fix: preserve complete Adapty metric responses"
```

---

## Task 2: Build one five-request snapshot per application

**Files:**

- Modify: `tests/test_adapty_client.py`
- Modify: `adapty_client.py`

### Step 1: Write a failing application-snapshot test

Patch `_fetch_chart` and `_fetch_conversion`, invoke a new `_fetch_app_snapshot`, and assert the exact output:

```python
result = _fetch_app_snapshot(
    app_index=0,
    app_key="sanitized-key",
    app_name="Unfollowers: Follow & Unfollow",
    is_visible=True,
    base_url="https://api-admin.adapty.io",
    analytics_path="api/v1/client-api/metrics/analytics/",
    conversion_path="api/v1/client-api/metrics/funnel/",
    timezone="Europe/Minsk",
    month_start=datetime(2026, 8, 1),
    previous_date=datetime(2026, 8, 5),
    report_date=datetime(2026, 8, 6),
)

self.assertEqual(result["mrr_total"], 1272.87)
self.assertEqual(result["mrr_delta_24h"], -107.86)
self.assertEqual(result["arr_total"], 15274.39)
self.assertEqual(result["arr_delta_24h"], -1294.33)
self.assertEqual(result["revenue_total"], 262.99)
self.assertEqual(result["revenue_per_day"], 11.90)
self.assertEqual(result["installs_total"], 1793)
self.assertEqual(result["installs_delta_24h"], 321)
self.assertEqual(result["conv_rate"], 0.8365867261572784)
self.assertEqual(result["conv_from"], 1793)
self.assertEqual(result["conv_to"], 15)
```

Configure the mocks to return:

- MRR: `ChartMetric(1272.87, (1380.73, 1272.87))`;
- ARR: `ChartMetric(15274.39, (16568.72, 15274.39))`;
- Revenue: `ChartMetric(262.99, (40.0, 30.0, 46.59, 32.65, 11.90))`;
- Installs: `ChartMetric(1793.0, (300.0, 301.0, 283.0, 321.0))`;
- Conversion: `ConversionMetric(0.8365867261572784, 1793, 15)`.

Assert exactly four chart calls plus one conversion call. Assert MRR/ARR use `previous_date` through `report_date`, while Revenue/Installs/Conversion use `month_start` through `report_date`.

### Step 2: Run the test and observe RED

Run:

```bash
.venv/bin/python -m unittest tests.test_adapty_client.TestAppSnapshot -v
```

Expected failure: `_fetch_app_snapshot` does not exist and the current path issues nine requests.

### Step 3: Implement series helpers and the snapshot builder

Add:

```python
def _last_value(metric: Optional[ChartMetric]) -> Optional[float]:
    if metric is None or not metric.daily_values:
        return None
    return metric.daily_values[-1]


def _last_delta(metric: Optional[ChartMetric]) -> Optional[float]:
    if metric is None or len(metric.daily_values) < 2:
        return None
    return metric.daily_values[-1] - metric.daily_values[-2]
```

Implement `_fetch_app_snapshot` so:

- `mrr_total` and `arr_total` use `_last_value`, not the response summary;
- `mrr_delta_24h` and `arr_delta_24h` use `_last_delta`;
- `revenue_total` and `installs_total` use each response summary;
- `revenue_per_day` and `installs_delta_24h` use each response's final daily point;
- conversion exposes `conv_rate`, `conv_from`, and `conv_to`;
- no missing value is converted to zero.

Delete `fetch_metrics_for_app` and `_fetch_revenue_metric_last_two_days` after their call sites are removed. Update debug output to read `metric.value` when a debug command calls `_fetch_chart`.

### Step 4: Make `fetch_all_metrics` use the snapshot builder

Replace its nested nine-request job with a call to `_fetch_app_snapshot`. Keep the existing per-app parallelism, result ordering, and exception isolation. Extend the exception result with:

```python
"conv_from": None,
"conv_to": None,
```

### Step 5: Test edge cases

Add and observe failing tests before each corresponding implementation adjustment:

- a one-point MRR series yields a current value but `None` delta;
- an empty Revenue series retains its MTD value but returns `None` daily revenue;
- a zero Installs summary and zero daily point remain numeric zero;
- an API exception in one concurrent application yields a complete `None` row without changing the order of the other applications.

### Step 6: Verify and commit

Run:

```bash
.venv/bin/python -m unittest tests.test_adapty_client -v
.venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add adapty_client.py tests/test_adapty_client.py
git commit -m "fix: collect consistent five-request app snapshots"
```

---

## Task 3: Calculate auditable, fail-closed report totals

**Files:**

- Modify: `tests/test_report_builder.py`
- Modify: `report_builder.py`

### Step 1: Expand the standard report fixtures

Give every normal visible row all required fields:

```python
{
    "index": 0,
    "name": "App One",
    "mrr_total": 1000.5,
    "mrr_delta_24h": 50.25,
    "arr_total": 12006.0,
    "arr_delta_24h": 603.0,
    "revenue_total": 200.0,
    "revenue_per_day": 25.0,
    "installs_total": 5000,
    "installs_delta_24h": 120,
    "conv_rate": 1.2,
    "conv_from": 5000,
    "conv_to": 60,
    "is_visible": True,
}
```

Use a second row with `conv_from=3000` and `conv_to=30`, so the expected total conversion is `90 / 8000 * 100 = 1.125%`, rendered as `1.12%` by Python's two-decimal formatting.

### Step 2: Write and run a failing hidden-row totals test

Add a third row with large values and `is_visible=False`. Assert its name and every distinctive total contribution are absent. Assert total MRR, ARR, Revenue, daily downloads, and conversion equal only the two visible rows.

Run:

```bash
.venv/bin/python -m unittest tests.test_report_builder.TestReportBuilder.test_hidden_rows_are_excluded_from_every_total -v
```

Expected failure: the current builder excludes the hidden block but still adds its metrics to `Total`.

### Step 3: Filter rows before validation, rendering, and totals

At the start of `build_report`, use:

```python
all_rows = fetch_all_metrics(report_date=resolved_report_date)
rows = [row for row in all_rows if row.get("is_visible", True)]
anomalies = _detect_anomalies(rows)
```

Remove the inner visibility condition because every remaining row is displayable.

### Step 4: Write and run failing raw-conversion tests

Add tests that:

- expect `Total Conv. (месяц): 1.12%` from the summed counts;
- alter row-level `conv_rate` while keeping raw counts unchanged and prove the total does not change;
- set one visible row's `conv_from` to `None` and expect total conversion `N/A`;
- keep `conv_from=0`, `conv_to=0` for all visible rows and expect total conversion `N/A` because the denominator is zero.

Run the focused tests and observe failure from the current weighted-rate calculation.

### Step 5: Implement complete-only totals

Add:

```python
def _sum_complete(rows: list[dict], key: str) -> Optional[float]:
    values = [row.get(key) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(float(value) for value in values)
```

Calculate MRR, ARR, Revenue, and each displayed delta independently with `_sum_complete`. Calculate total conversion only when all visible rows have `conv_from` and `conv_to` and the summed denominator is positive:

```python
conv_from = _sum_complete(rows, "conv_from")
conv_to = _sum_complete(rows, "conv_to")
total_conv = (
    conv_to / conv_from * 100
    if conv_from is not None and conv_to is not None and conv_from > 0
    else None
)
```

Use `_fmt_num` and `_fmt_delta` directly on optional totals so an incomplete metric renders `N/A` rather than a plausible partial sum. Preserve zero as a valid number.

### Step 6: Expand anomaly validation

Write failing assertions that missing Revenue, ARR, conversion percentage, or either conversion raw count identifies the application and field in `ReportBuildResult.anomalies`.

Extend `_detect_anomalies` to validate all displayed report fields. Keep the existing range checks and add:

- non-negative MRR, ARR, Revenue, installs, and conversion counts;
- `conv_to <= conv_from`;
- `conv_rate` within 0–100 when present.

Do not label a numeric zero as missing.

### Step 7: Verify and commit

Run:

```bash
.venv/bin/python -m unittest tests.test_report_builder -v
.venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add report_builder.py tests/test_report_builder.py
git commit -m "fix: scope report totals to complete visible rows"
```

---

## Task 4: Document the canonical application and metric contract

**Files:**

- Modify: `.env.example`
- Modify: `README.md`

### Step 1: Update the environment template

Set the three contiguous names exactly:

```dotenv
ADAPTY_APP_NAME_1=Unfollowers: Follow & Unfollow
ADAPTY_APP_NAME_2=Granny Photos
ADAPTY_APP_NAME_3=Otty: Couples&Relationships
```

Document that all configured slots are visible and included in totals. Remove wording suggesting hidden portfolio slots.

### Step 2: Update report semantics

In `README.md`, document:

- the canonical three-app portfolio;
- `Europe/Minsk` and new `device_id` install counting;
- gross `revenue` semantics;
- MRR/ARR current-point and daily-delta semantics;
- Revenue/Installs month summary plus final daily point;
- conversion total from summed `value_to / value_from`;
- late Adapty backfill as the reason an old Telegram snapshot may differ from today's view of the same historical date;
- fail-closed `N/A` totals when a displayed app is incomplete.

### Step 3: Verify no secret or stale application appears

Run:

```bash
rg -n "Calorie Tracker|TeaNote|ADAPTY_API_KEY_APP4|Api-Key [A-Za-z0-9]" .env.example README.md docs/superpowers
```

The design document may mention the two removed apps only in its root-cause history. No key value may match.

### Step 4: Commit

```bash
git add .env.example README.md
git commit -m "docs: define canonical Adapty report portfolio"
```

---

## Task 5: Run local verification and production-data preview

**Files:**

- No repository changes expected
- Read Railway production variables through the linked service without printing secret values

### Step 1: Run static and complete test verification

Run:

```bash
.venv/bin/python -m compileall -q .
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

All commands must exit zero.

### Step 2: Build a report preview without Telegram

Run the report builder with Railway variables injected and print only the resulting report text:

```bash
RAILWAY_CALLER="skill:use-railway@1.3.7" \
RAILWAY_AGENT_SESSION="railway-skill-adapty-metrics-20260807" \
railway run .venv/bin/python -c 'from datetime import date; from report_builder import build_report_text; print(build_report_text(date(2026, 8, 6)))'
```

Do not call `--test-send` and do not import Telegram delivery functions.

### Step 3: Reconcile the three applications

For the same 1–6 August range, `Europe/Minsk`, and new `device_id` install rule, compare each displayed application and Total for:

- MRR current value and 5→6 August delta;
- ARR current value and 5→6 August delta;
- Revenue month value and 6 August contribution;
- Installs month value and 6 August contribution;
- Install→Paid percentage and raw counts.

Treat a current Adapty backfill as explained only when the current Export API and Dashboard agree at the same snapshot. Stop the release for any same-snapshot mismatch.

---

## Task 6: Configure the canonical production portfolio securely

**Files:**

- Modify: Railway production variables only
- Read: Adapty application settings for Otty only

### Step 1: Confirm the exact target by name

Use Railway with the required caller/session environment and confirm:

- project `Adapty Stats TG Bot`;
- environment `production`;
- service `worker`.

Read variable names and non-secret application names only. Do not emit Secret API values.

### Step 2: Transfer Otty's Secret API key safely

Open `Otty: Couples&Relationships` in Adapty application settings and use the Secret API key intended for Export API access. Because this transfers authentication material from Adapty to Railway, obtain the required action-time user confirmation immediately before the write. Enter the key through a non-echoing input path and write it to `ADAPTY_API_KEY_APP3` without placing it in terminal history or captured command output.

Set:

```text
ADAPTY_APP_NAME_1=Unfollowers: Follow & Unfollow
ADAPTY_APP_NAME_2=Granny Photos
ADAPTY_APP_NAME_3=Otty: Couples&Relationships
```

### Step 3: Remove stale slots and visibility overrides

Delete these production variables after the three canonical names and keys read back successfully:

```text
ADAPTY_API_KEY_APP4
ADAPTY_APP_NAME_4
ADAPTY_APP_VISIBLE_1
ADAPTY_APP_VISIBLE_2
ADAPTY_APP_VISIBLE_3
ADAPTY_APP_VISIBLE_4
```

Do not remove or modify Telegram, A/B, Apple Ads, schedule, or dashboard credentials.

### Step 4: Re-run the no-send preview

Build a fresh report for the current date and for 6 August 2026. Require exactly these three application blocks in order, no anomaly banner, and totals equal to their visible contributions.

---

## Task 7: Review, integrate, deploy, and verify Railway

**Files:**

- Merge reviewed commits from `codex/adapty-metric-parity` into `main`
- Push the tested `main` commit to `origin`

### Step 1: Review the implementation

Read and follow `superpowers:requesting-code-review`. Inspect the diff against the design for:

- all five metric definitions;
- exactly five requests per app;
- no `proceeds` fallback;
- visible-only totals;
- raw-count conversion total;
- complete-only totals;
- unchanged A/B and Apple Ads paths.

Address every correctness or security finding and rerun focused tests for changed code.

### Step 2: Perform completion verification

Read and follow `superpowers:verification-before-completion`, then run from a clean worktree:

```bash
.venv/bin/python -m compileall -q .
.venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short
```

Require zero exit codes and only intentional untracked/modified files before commit. Commit any final reviewed changes.

### Step 3: Integrate using the branch-finishing workflow

Read and follow `superpowers:finishing-a-development-branch`. With the user's standing instruction to use best judgment, select local merge into `main`, rerun the full suite on integrated `main`, and push `main` to `origin` only after the merge verification passes.

### Step 4: Deploy the tested commit

Use the Railway skill caller/session variables for every CLI command. Wait until the `worker` deployment reaches terminal `SUCCESS`; a build success without a successful runtime deployment is insufficient.

### Step 5: Verify runtime and live report parity

Inspect startup and runtime logs for import errors, scheduler errors, repeated API failures, and leaked secret material. Run one final no-send report preview in production and reconcile it with a same-snapshot Adapty view. Do not send an extra Telegram report during verification.

### Step 6: Final evidence

Record in the handoff:

- final commit hash;
- full test count and zero failures;
- Railway deployment ID and `SUCCESS` state;
- the three configured application names;
- per-metric parity result or an explicitly quantified Adapty backfill;
- confirmation that no Telegram message was sent during preview.

## Done When

- The report displays exactly Unfollowers, Granny Photos, and Otty.
- Every Total value is calculated only from those three displayed rows.
- MRR, ARR, Revenue, Installs, and conversion match Adapty for the same snapshot and filters.
- Four chart responses plus one conversion response are used per application.
- Missing displayed-app data produces `N/A`, never a partial plausible total.
- The complete test suite passes on the feature branch and integrated `main`.
- Railway production runs the tested commit successfully with the canonical three-slot configuration.
