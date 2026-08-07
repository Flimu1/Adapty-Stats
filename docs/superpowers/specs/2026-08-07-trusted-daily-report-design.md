# Trusted Adapty Daily Report Design

## Goal

Make every numeric value in the main Telegram daily report safe to trust. A
value is published only after its application scope, Adapty source, date
window, response shape, numeric type, and reconciliation rules pass. A failed
check affects only that metric and its corresponding portfolio total; it is
rendered as `N/A` with a visible reason.

This design cannot prevent Adapty from backfilling historical installs or
conversions. It guarantees that the bot reports a clearly timestamped snapshot
and never disguises missing, malformed, out-of-scope, or internally
inconsistent data as a valid number.

## Confirmed Historical Root Causes

The previous report combined incompatible scopes and weak failure handling:

- Telegram rendered Unfollowers and Granny Photos while `Total` silently
  included hidden Calorie Tracker and TeaNote rows. Those hidden contributions
  produced unexplained dollars in MRR, ARR, and Revenue.
- Related values were fetched through overlapping requests at different
  moments, so a summary and its parenthetical daily value could describe
  different Adapty snapshots.
- Missing API values were allowed to become plausible partial totals.
- The report warned about anomalies but still presented affected numbers in
  the same form as trusted values.
- Adapty can revise historical installs and cohort conversion after the daily
  Telegram message has been sent. This is legitimate upstream backfill, not a
  stable historical ledger.

The first parity change already removed hidden-row totals, uses one response
per related value pair, preserves conversion raw counts, rate-limits requests,
and fails closed for incomplete totals. This design adds a permanent portfolio
contract, per-metric quarantine, arithmetic reconciliation, and auditable
trust status.

## Trust Invariant

The main report obeys this invariant:

> Every numeric portfolio total is exactly reproducible from the three numeric
> application values displayed immediately above it. If any required
> application value is not trusted, that total is `N/A`.

No hidden application, API-provided portfolio total, default zero, cached
historical value, `proceeds`, or `net_revenue` value may enter the calculation.

## Canonical Portfolio Contract

The daily report contains exactly these ordered slots:

1. `Unfollowers: Follow & Unfollow`
2. `Granny Photos`
3. `Otty: Couples&Relationships`

The contract is separate from the generic Adapty application loader used by
the A/B and Apple Ads reports.

For the daily report:

- slots 1–3 must have exact names and non-empty Secret API keys;
- all three slots are visible;
- `ADAPTY_APP_VISIBLE_*` does not control daily report scope;
- APP4 and later slots are ignored and reported as stale configuration;
- an incorrect or missing canonical slot becomes an all-`N/A` application row
  with a configuration issue; correctly configured canonical slots can still
  be collected;
- extra slots can never contribute to application rows or totals.

Secret key values are excluded from dataclass representations, logs, errors,
tests, report text, and audit records.

## Metric Provenance

All main-report metrics use the documented Adapty Export API with
`Adapty-Tz: Europe/Minsk` and gross `data.revenue` where applicable.

Each trusted metric records non-secret provenance internally:

- application name and canonical slot;
- metric name;
- endpoint class (`analytics` or `conversion`);
- requested date window;
- expected report date;
- validation status and issue code.

The report does not display implementation details, but logs one structured
audit line per application metric and per portfolio total.

## Validation Pipeline

Validation occurs in layers so malformed input cannot become a plausible
Telegram number.

### Transport and Response Layer

- Requests share one session per application.
- Sequential calls are paced to no more than two starts per second.
- HTTP 429 and transient 5xx responses use bounded retry behavior and honor
  `Retry-After`.
- A transport failure, non-JSON response, missing gross series, or unsupported
  response shape invalidates only the affected metric family.

### Numeric Layer

- Booleans, NaN, infinity, numeric strings with invalid content, and missing
  values are invalid.
- Installs and conversion counts must be non-negative mathematical integers;
  fractional counts are invalid and are never truncated.
- MRR, ARR, Revenue, and their current daily points must be finite and
  non-negative.
- MRR, ARR, and Revenue deltas may be negative because portfolio performance
  can decline.
- Conversion percentage must be finite and within 0–100.
- Zero is valid and remains distinct from missing data.

### Date and Series Layer

- Adapty timestamp labels are normalized to `YYYY-MM-DD`.
- MRR and ARR require exact points for the previous calendar date and report
  date; current value and delta are invalid if either expected date is absent.
- Revenue and Installs MTD summaries use a request from the first of the month
  through the report date.
- Their parenthetical daily values require a final point whose normalized date
  equals the report date.
- A stale or out-of-order final point is invalid, not silently treated as the
  report date.

### Within-Metric Reconciliation

- Revenue MTD must be greater than or equal to the non-negative report-day
  Revenue point.
- Installs MTD must be greater than or equal to report-day Installs.
- Conversion requires `value_to <= value_from`.
- When `value_from > 0`, the returned conversion percentage must match
  `value_to / value_from * 100` within `0.01` percentage point.
- When `value_from == 0`, `value_to` and the returned percentage must both be
  zero.

### Cross-Metric Reconciliation

- ARR is sourced from Adapty and is never calculated for display.
- As an integrity check, trusted ARR must equal trusted MRR multiplied by 12
  within `$0.05` for both the current value and daily delta.
- An ARR mismatch quarantines ARR only. MRR remains independently trusted.

### Portfolio Reconciliation

- Each total is recomputed from the canonical application rows.
- A total is numeric only when all three canonical application values required
  by that total are trusted.
- Total conversion is `sum(value_to) / sum(value_from) * 100`; displayed
  application percentages are never averaged.
- A zero summed conversion denominator produces `N/A`, not `0.00%`.
- Every computed total is checked once more against the same displayed source
  values before formatting.

## Per-Metric Quarantine

Each application result carries values plus metric issue codes. Validation
never substitutes a fallback source.

Examples:

- Invalid Otty Revenue makes Otty Revenue and Total Revenue `N/A`; Otty MRR,
  Installs, and conversion remain visible if trusted.
- Missing Granny conversion raw counts make Granny conversion and Total
  conversion `N/A`; its monetary metrics remain visible.
- A missing Otty key makes every Otty metric and every portfolio total `N/A`,
  while trusted Unfollowers and Granny values remain visible for reference.

The report opens with a warning when any metric is quarantined and lists the
application, metric, and concise non-secret reason. Trusted values retain their
normal format. An `N/A` value never carries a numeric parenthetical delta.

## Trust Status in Telegram

When every check passes, the report ends with:

`✅ Проверка данных: пройдена`

When one or more checks fail, the report ends with:

`⚠️ Проверка данных: обнаружено N проблем — недостоверные метрики показаны как N/A`

`N` includes both quarantined metric families and non-metric configuration
issues such as ignored stale APP4 variables.

The main report is still delivered under the user's selected partial
degradation policy. The scheduler and manual collection paths also send a
detailed anomaly notification to `TELEGRAM_ADMIN_ID` when configured.

The A/B and Apple Ads follow-up reports remain independent. A quarantined main
metric neither changes nor suppresses those reports.

## Audit Logging

One structured, secret-free log event is emitted for every collection:

- `report_date`, `snapshot_timezone`, and canonical portfolio version;
- application slot and name;
- metric and validation status;
- non-secret issue code for invalid metrics;
- whether each total was computed or quarantined.

Raw API response bodies, authorization headers, Telegram tokens, Adapty keys,
and Railway variables are never logged.

The audit record makes future discrepancies traceable without relying on the
Telegram text alone.

## Testing

TDD regression coverage must demonstrate:

- exact canonical slot order and names;
- missing APP3, wrong name, visibility overrides, and APP4 cannot contribute;
- extra configured applications are ignored and flagged;
- every transport, numeric, date, and reconciliation rule above;
- per-metric quarantine does not erase unrelated trusted metrics;
- each total becomes `N/A` when one required canonical value is invalid;
- total conversion uses raw counts;
- zero remains valid;
- normal reports show the passed trust marker;
- partial reports show the warning marker and issue details;
- scheduled, test-send, and manual collection paths deliver the same validated
  report behavior;
- A/B and Apple Ads behavior remains unchanged;
- the 4–6 August examples and later backfill remain valid timestamped snapshots.

The complete existing suite must remain green.

## Production Rollout

Before enabling the strict portfolio contract in production:

1. securely replace APP3 with Otty's Secret API key and exact name;
2. remove Calorie Tracker, TeaNote, APP4, and visibility overrides;
3. run a no-send preview for 6 August and the current closed day;
4. compare the three applications and totals with Adapty using the same
   timezone, date range, gross Revenue series, and new `device_id` install rule;
5. require all integrity checks to pass or explicitly show `N/A` for the
   affected metric;
6. deploy the tested commit and require Railway terminal `SUCCESS`;
7. inspect secret-free startup and audit logs;
8. do not send an extra Telegram message during rollout verification.

Transferring Otty's Secret API key from Adapty to Railway requires explicit
action-time confirmation. The value is copied through a non-echoing path and
never appears in tool output.

## Out of Scope

- Treating old Telegram snapshots as immutable Adapty history.
- Replacing the documented Export API with private Dashboard endpoints.
- Adding applications beyond the canonical three.
- Changing A/B or Apple Ads metric definitions.
- Claiming that upstream Adapty data can never be revised.
