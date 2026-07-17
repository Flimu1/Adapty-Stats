# Stable Adapty A/B Secret API Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the expiring Dashboard-token A/B collector with a Secret-Key collector that produces the approved unique-view Telegram report, then verify, publish, deploy, enable, and send it once.

**Architecture:** A focused `AdaptyAbExportClient` makes three experiment- and paywall-scoped Analytics Export requests per variant (`revenue`, `paywall_view_paid`, and `refund_events`), validates every field, and derives purchases and ARPAS. `ab_test_report.py` maps the two immutable variants and owns only configuration plus exact Telegram formatting. Any incomplete request fails the entire report before Telegram delivery.

**Tech Stack:** Python 3.11, `requests`, `urllib3.Retry`, `unittest`, Telegram Bot HTTP API, Railway CLI.

## Global Constraints

- Production collection uses only `Authorization: Api-Key <Secret API Key>`; no Dashboard/WebView session is used by the A/B path.
- Every metrics request includes date, `paywall_id`, and `placement_audience_version_id` filters.
- Variant A is Old Prices; variant B is New Prices.
- `Unique paywall views` and `CR unique view→purchase` are named explicitly in Telegram.
- The Telegram message contains only the approved metrics and leader line.
- No partial report is formatted or sent.
- Secrets never appear in source, tests, docs, previews, or logs.
- Keep `AB_TEST_REPORT_ENABLED=false` in Railway until the deployed commit is healthy and live parity is accepted.

---

### Task 1: Build the strict Secret-Key A/B metrics client

**Files:**
- Create: `adapty_ab_export.py`
- Create: `tests/test_adapty_ab_export.py`

**Interfaces:**
- Consumes: an app Secret API Key, Export API base URL/path/timezone, experiment ID, paywall ID, start date, and end date.
- Produces: `AdaptyAbExportClient.fetch_variant(...) -> AdaptyAbVariantMetrics` and `AdaptyAbExportError` for every unusable result.

- [ ] **Step 1: Write failing contract tests for the three requests and derived values**

```python
def test_fetch_variant_scopes_every_request_and_derives_dashboard_aligned_metrics():
    session = MagicMock()
    session.post.side_effect = [
        response({"data": {"revenue": {"value": 86.11157593263285}}}),
        response({"data": {"common": {"value_from": 570, "value_to": 8}}}),
        response({"data": {"common": {"value": 1}}}),
    ]
    client = AdaptyAbExportClient(
        "secret-test", session=session, request_interval=0
    )

    result = client.fetch_variant(
        label="A",
        paywall_id="old-paywall",
        test_id="test-123",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 17),
    )

    assert result.revenue == 86.11157593263285
    assert result.unique_views == 570
    assert result.purchases == 9
    assert round(result.arpas, 2) == 9.57
    assert [call.kwargs["json"]["chart_id"] for call in session.post.call_args_list] == [
        "revenue", "paywall_view_paid", "refund_events"
    ]
    for call in session.post.call_args_list:
        assert call.kwargs["json"]["filters"] == {
            "date": ["2026-07-10", "2026-07-17"],
            "paywall_id": ["old-paywall"],
            "placement_audience_version_id": ["test-123"],
        }
        assert call.kwargs["headers"]["Authorization"] == "Api-Key secret-test"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_adapty_ab_export -v`

Expected: FAIL because `adapty_ab_export` does not exist.

- [ ] **Step 3: Implement the minimal client and value validation**

```python
class AdaptyAbExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdaptyAbVariantMetrics:
    label: str
    paywall_id: str
    revenue: float
    unique_views: int
    purchases: int
    arpas: float

    @property
    def conversion_rate(self) -> float:
        return 0.0 if self.unique_views == 0 else self.purchases / self.unique_views * 100


class AdaptyAbExportClient:
    def fetch_variant(self, *, label, paywall_id, test_id, start_date, end_date):
        revenue_payload = self._fetch_chart("revenue", paywall_id, test_id, start_date, end_date)
        conversion_payload = self._fetch_chart(
            "paywall_view_paid", paywall_id, test_id, start_date, end_date
        )
        refund_payload = self._fetch_chart(
            "refund_events", paywall_id, test_id, start_date, end_date
        )
        revenue = _nonnegative_float(revenue_payload, ("data", "revenue", "value"))
        unique_views = _nonnegative_int(
            conversion_payload, ("data", "common", "value_from")
        )
        paid_profiles = _nonnegative_int(
            conversion_payload, ("data", "common", "value_to")
        )
        refunds = _nonnegative_int(refund_payload, ("data", "common", "value"))
        purchases = paid_profiles + refunds
        arpas = 0.0 if purchases == 0 else revenue / purchases
        return AdaptyAbVariantMetrics(
            label, paywall_id, revenue, unique_views, purchases, arpas
        )
```

Use a `requests.Session` configured with `Retry(total=3, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["POST"], respect_retry_after_header=True)` and sleep at least `0.55` seconds between calls in production. Explicitly send `period_unit="day"`, `date_type="purchase_date"`, `format="json"`, and `Adapty-Tz`.

- [ ] **Step 4: Add one failing test at a time for invalid data and verify RED/GREEN**

Cover HTTP 401/403, HTTP 429/5xx after retries, invalid JSON, missing nested fields, booleans/non-numbers, negative metrics, fractional counts, zero views, and purchases without views. Each case must raise `AdaptyAbExportError` without including response bodies or credentials in its message.

- [ ] **Step 5: Run the focused client tests**

Run: `python3 -m unittest tests.test_adapty_ab_export -v`

Expected: all client tests PASS with no warnings.

- [ ] **Step 6: Commit the client**

```bash
git add adapty_ab_export.py tests/test_adapty_ab_export.py
git commit -m "feat: collect A/B metrics with Adapty Secret API"
```

---

### Task 2: Replace the report data path and lock the Telegram golden format

**Files:**
- Modify: `ab_test_report.py`
- Modify: `tests/test_ab_test_report.py`
- Modify: `config.py`
- Delete: `adapty_ab_dashboard.py`
- Delete: `tests/test_adapty_ab_dashboard.py`

**Interfaces:**
- Consumes: `AdaptyAbExportClient` and the existing A/B environment mapping.
- Produces: `build_ab_test_report(report_date: Optional[date]) -> Optional[str]` with exact HTML output.

- [ ] **Step 1: Replace substring assertions with one failing golden-message test**

```python
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
assert build_ab_test_report(date(2026, 7, 17)) == expected
```

- [ ] **Step 2: Run the golden test and verify RED**

Run: `python3 -m unittest tests.test_ab_test_report.TestAbTestReport.test_formats_exact_approved_unique_view_report -v`

Expected: FAIL because the current report includes Dashboard-only fields and different copy.

- [ ] **Step 3: Make configuration depend on the app Secret Key, not Dashboard identity**

Remove `dashboard_app_id` and `dashboard_token` from `AbTestConfig`. Keep `AB_TEST_ID`, the start date, and strict A/B label/paywall/name mapping. Resolve the Secret Key through `get_adapty_apps()[app_index - 1]`; do not add a second secret variable.

- [ ] **Step 4: Delegate collection to the new client**

```python
client = AdaptyAbExportClient(
    api_key=app.api_key,
    base_url=get_adapty_base_url(),
    analytics_path=get_adapty_analytics_path(),
    timezone=get_adapty_timezone(),
)
rows = [
    client.fetch_variant(
        label=variant.label,
        paywall_id=variant.paywall_id,
        test_id=config.test_id,
        start_date=config.start_date,
        end_date=report_date,
    )
    for variant in (config.variant_a, config.variant_b)
]
```

Map the returned rows back to configured paywall names. Require exactly A then B and two distinct paywall IDs.

- [ ] **Step 5: Implement only the approved formatter**

Remove source, snapshot, revenue-per-1K, proceeds, net proceeds, P2BB, and latency lines. Format money to two decimals, counts with thousands separators, conversion to two decimals, HTML-escape names, and calculate the leader delta from unrounded revenue.

- [ ] **Step 6: Add fail-closed tests**

Add tests proving disabled reports do not call Adapty, a missing Secret Key/config field raises before collection, a client error propagates, zero views never divides by zero, reversed labels are rejected, and partial rows cannot be formatted.

- [ ] **Step 7: Remove the obsolete Dashboard A/B client and run report tests**

Run: `python3 -m unittest tests.test_ab_test_report tests.test_config tests.test_telegram_sender -v`

Expected: PASS; `rg -n "AdaptyAbDashboardClient|ADAPTY_DASHBOARD_TOKEN" ab_test_report.py tests/test_ab_test_report.py` returns no matches.

- [ ] **Step 8: Commit the report replacement**

```bash
git add ab_test_report.py config.py tests/test_ab_test_report.py
git rm adapty_ab_dashboard.py tests/test_adapty_ab_dashboard.py
git commit -m "fix: report A/B metrics through Secret API"
```

---

### Task 3: Add a safe preview command and update operational documentation

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Produces: `python main.py --preview-ab-report`, which builds and prints one report without calling Telegram.

- [ ] **Step 1: Write failing CLI preview tests**

```python
@patch("ab_test_report.build_ab_test_report", return_value="preview")
@patch("sys.argv", ["main.py", "--preview-ab-report"])
def test_preview_ab_report_prints_without_sending(mock_build):
    with patch("builtins.print") as output, patch("telegram_sender.send_message") as send:
        main.main()
    output.assert_called_once_with("preview")
    send.assert_not_called()
```

Also test that a disabled/empty preview exits with code 1.

- [ ] **Step 2: Run preview tests and verify RED**

Run: `python3 -m unittest tests.test_main -v`

Expected: FAIL because the CLI flag does not exist.

- [ ] **Step 3: Add the preview branch before all sending branches**

```python
parser.add_argument(
    "--preview-ab-report",
    action="store_true",
    help="Собрать A/B-отчёт и вывести его без отправки в Telegram",
)
if args.preview_ab_report:
    from ab_test_report import build_ab_test_report
    text = build_ab_test_report()
    if not text:
        logger.error("A/B report is disabled or empty")
        raise SystemExit(1)
    print(text)
    return
```

- [ ] **Step 4: Document exact production variables and semantics**

Update `.env.example` and README so A/B setup requires `ADAPTY_API_KEY_APP1`, `AB_TEST_ID`, start date, and variant mappings. State that views/CR are unique-view metrics. Move Dashboard token/app/company variables wholly under Apple Ads and never call them A/B requirements.

- [ ] **Step 5: Run CLI tests and the complete suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS with no warnings or secret-like output.

- [ ] **Step 6: Commit preview and docs**

```bash
git add main.py tests/test_main.py .env.example README.md docs/ARCHITECTURE.md
git commit -m "docs: operationalize Secret API A/B reporting"
```

---

### Task 4: Verify live parity, publish, deploy, enable, and send once

**Files:**
- No production source changes expected.

**Interfaces:**
- Consumes: the complete tested repository and protected Railway variables.
- Produces: one healthy Railway release and one Telegram A/B report in the configured general chat.

- [ ] **Step 1: Run final local verification**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q .
git diff --check
git status --short
```

Expected: all tests PASS, compilation succeeds, no whitespace errors, and only intended plan-tracking changes remain.

- [ ] **Step 2: Build a live dry-run with Railway secrets while production delivery remains disabled**

Run:

```bash
RAILWAY_CALLER=skill:use-railway@1.2.3 \
RAILWAY_AGENT_SESSION=railway-skill-20260717-adapty-approx \
railway run env AB_TEST_REPORT_ENABLED=true python3 main.py --preview-ab-report
```

Expected: two complete variants, A Old/B New, and no credential values.

- [ ] **Step 3: Reconcile the preview against the same Dashboard snapshot**

Verify Revenue, Purchases, and ARPAS exactly. Compare `Unique paywall views` and unique CR with Dashboard's Unique columns, allowing only the documented short views-refresh lag. Abort release on mapping reversal, missing data, or unexplained drift.

- [ ] **Step 4: Review the full diff and commit any plan checkbox updates**

Run: `git diff --stat && git diff --check && git log --oneline -5`.

- [ ] **Step 5: Push verified main to GitHub**

Run: `git push origin main`.

Expected: `origin/main` resolves to the verified local HEAD.

- [ ] **Step 6: Verify the automatic Railway deploy while A/B remains disabled**

Check `railway status --json` and bounded build/runtime logs until the deployment for local HEAD is `SUCCESS` and its instance is `RUNNING`.

- [ ] **Step 7: Enable the production A/B report and verify the restarted deployment**

Run: `railway variable set AB_TEST_REPORT_ENABLED=true --service worker`, then read the variable back without printing other secret values. Wait for the resulting deployment to be `SUCCESS/RUNNING` and confirm startup logs contain no A/B/authentication errors.

- [ ] **Step 8: Send exactly one report through the production bot**

Run:

```bash
RAILWAY_CALLER=skill:use-railway@1.2.3 \
RAILWAY_AGENT_SESSION=railway-skill-20260717-adapty-approx \
railway run env AB_TEST_REPORT_ENABLED=true python3 main.py --send-ab-report
```

Expected: exit code 0 and one `A/B report sent` log line. Do not retry automatically if the command reaches Telegram but its final output is ambiguous; inspect Telegram/API-safe logs first to prevent duplication.

- [ ] **Step 9: Perform final production verification**

Confirm GitHub main, Railway deployment commit, local HEAD, and the one-shot report all agree. Re-run a non-sending preview and inspect bounded logs for credential leakage, authentication errors, scheduler crashes, or duplicate sends.

