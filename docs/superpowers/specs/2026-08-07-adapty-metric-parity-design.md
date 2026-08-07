# Adapty Metric Parity Design

## Goal

Make the daily Telegram report reconcile with Adapty Dashboard when both
surfaces use the same date range, timezone, install-counting rule, revenue
series, and application set.

The canonical application set is explicit and contains exactly:

1. `Unfollowers: Follow & Unfollow`
2. `Granny Photos`
3. `Otty: Couples&Relationships`

Every canonical application is visible in the Telegram report. A metric in the
`Total` block is calculated only from the application rows displayed above it.

## Confirmed Root Causes

The existing implementation mixes three incompatible scopes:

- Adapty Overview contains seven applications.
- Railway configures four Secret API keys: Unfollowers, Granny Photos,
  Calorie Tracker, and TeaNote.
- Telegram displays only Unfollowers and Granny Photos, while its `Total`
  silently includes Calorie Tracker and TeaNote.

The visible application-level metrics already reconcile with Adapty Export API
and Dashboard for the same filters. Historical installs and cohort conversion
can change after a report is sent because Adapty backfills installs and users
can convert after their install date. A daily report is therefore a snapshot,
not an immutable historical ledger.

## Canonical Metric Definitions

All timestamps and date boundaries use `Europe/Minsk` (`GMT+3`). All monetary
values use Adapty's gross `revenue` series in USD, matching the selected
Dashboard cards rather than `proceeds` or `net_revenue`.

### MRR

- Endpoint: Analytics Export API, `chart_id=mrr`.
- Series: `data.revenue`.
- Current value: the final daily point for the report date.
- Daily delta: final daily point minus the immediately preceding daily point.
- Request window: the previous calendar day through the report date.

### ARR

- Endpoint: Analytics Export API, `chart_id=arr`.
- Series: `data.revenue`.
- Current value and delta follow the MRR rules.
- ARR remains sourced from Adapty; the bot does not derive it as `MRR * 12`.

### Revenue

- Endpoint: Analytics Export API, `chart_id=revenue`.
- Series: `data.revenue`.
- Month value: `data.revenue.value` for the first day of the month through the
  report date.
- Parenthetical value: revenue attributed to the report date, taken from the
  final daily point in the same response.

### Installs

- Endpoint: Analytics Export API, `chart_id=installs`.
- Series: `data.common`.
- Month value: `data.common.value` for the first day of the month through the
  report date.
- Parenthetical value: installs attributed to the report date, taken from the
  final daily point in the same response.
- Dashboard comparison must use `Count installs as new device_ids`.

### Install to Paid Conversion

- Endpoint: Conversion Export API.
- Window: first day of the month through the report date.
- Parameters: `from_period=null`, `to_period=1`,
  `date_type=profile_install_date`, and `period_unit=month`.
- Application value: the returned `value` percentage.
- Reconciliation counts: `value_from` is eligible installs and `value_to` is
  paid users.
- Total value: `sum(value_to) / sum(value_from) * 100` across displayed apps.
  The total is never an average of application percentages.

## Data Flow

Each application performs five API requests:

1. two-day MRR;
2. two-day ARR;
3. month-to-date Revenue;
4. month-to-date Installs;
5. month-to-date Install to Paid conversion.

The response parser returns both the summary value and the daily points rather
than discarding the series. MRR and ARR totals and deltas come from their
respective two-day response. Revenue and installs month values and daily values
come from one response each. This prevents values in the same report from being
calculated from overlapping requests observed at slightly different moments.

The application result passed to the report builder contains:

- MRR value and daily delta;
- ARR value and daily delta;
- Revenue MTD and report-day value;
- Installs MTD and report-day value;
- conversion percentage, eligible-install count, and paid-user count;
- application identity and visibility.

The report builder filters to visible rows before both rendering and totals.
This enforces the invariant that every contribution to `Total` is auditable in
the message.

## Missing and Partial Data

Missing application metrics are not converted to zero.

- The affected application displays `N/A` for that metric.
- A total metric displays `N/A` when any displayed application is missing the
  corresponding value or reconciliation counts.
- The anomaly banner identifies the application and missing metric.
- Zero remains a valid value and is distinct from missing data.

This fail-closed total policy prevents a partial API failure from producing a
plausible but understated portfolio result.

## Railway Configuration

Production uses three contiguous application slots:

- `ADAPTY_API_KEY_APP1` / `ADAPTY_APP_NAME_1` — Unfollowers;
- `ADAPTY_API_KEY_APP2` / `ADAPTY_APP_NAME_2` — Granny Photos;
- `ADAPTY_API_KEY_APP3` / `ADAPTY_APP_NAME_3` — Otty.

Otty's Secret API key must be copied from Adapty to Railway without printing or
logging it. The old Calorie Tracker and TeaNote slots and visibility overrides
are removed after the new configuration has been read back by name and tested.
Secret values are never included in logs, commits, tests, or report text.

## Testing

Tests use representative Adapty JSON fixtures and must cover:

- extracting gross MRR/ARR current values and two-day deltas;
- extracting Revenue MTD and the report-day contribution from one response;
- extracting Installs MTD and report-day installs from one response;
- preserving conversion `value`, `value_from`, and `value_to`;
- computing total conversion from summed raw counts;
- excluding hidden rows from every total;
- returning `N/A` totals when a displayed row is missing data;
- treating zero as valid data;
- the 4–6 August report shapes, including late backfill without assuming that a
  prior Telegram snapshot must equal today's historical Dashboard value.

The TDD cycle must demonstrate each regression test failing before the minimal
production change and passing afterward. The complete existing test suite must
remain green.

## Live Verification and Deployment

Before deployment:

1. run the complete local test suite;
2. preview a report with production Railway variables without sending Telegram;
3. filter Adapty Overview to 1–6 August, `GMT+3`, new `device_id` installs, and
   the three canonical applications;
4. reconcile each application and Total for MRR, ARR, Revenue, Installs, and
   Install to Paid conversion;
5. record any remaining difference as an explained Adapty backfill or block the
   release if it is unexplained.

After the user approves transmitting Otty's Secret API key to Railway, update
the production variables. Deploy only the tested commit, wait for Railway to
reach terminal `SUCCESS`, inspect startup/runtime logs, and verify the next
preview before enabling normal scheduled delivery.

## Out of Scope

- Changing Adapty Dashboard settings.
- Using undocumented Dashboard endpoints as the report source.
- Adding applications other than the three canonical apps.
- Treating a historical Telegram snapshot as immutable Adapty history.
- Changing the A/B test or Apple Ads reports.
