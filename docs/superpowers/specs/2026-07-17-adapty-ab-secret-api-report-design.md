# Stable Adapty A/B Report via Secret API Design

## Goal

Replace the expiring Dashboard Bearer-token dependency with a stable server-to-server collector that uses the app's Adapty Secret API Key and produces the approved Telegram A/B report for the active paywall-price experiment.

## Scope and metric semantics

The report is specific to experiment `1db6e378-026f-4634-9522-ec4fa95deb99`, starting on `2026-07-10`, with this verified variant mapping:

- A: `d6d24875-e330-4ad9-8ee0-841d3452a911` — `New Paywall Old Prices`
- B: `d6765d7f-eb06-42db-8d0d-ee21e2b41fe8` — `New Paywall New Prices`

Each request includes the report date range, `paywall_id`, and `placement_audience_version_id`. A live request with a fake experiment ID returned zero for both revenue and View-to-Paid, confirming that the experiment filter is applied by the current API implementation.

The report uses these Secret-API metrics:

| Telegram metric | Source and calculation | Meaning |
| --- | --- | --- |
| Revenue | `chart_id=revenue`, `data.revenue.value` | Experiment- and variant-scoped gross revenue after refunds. |
| Unique paywall views | `chart_id=paywall_view_paid`, `data.common.value_from` | Unique profiles that viewed the variant in the selected period. It deliberately does not claim to be repeated total views. |
| Purchases | `paywall_view_paid.value_to + refund_events.value` | Paid profiles plus refunded purchase events, restoring purchases removed from the View-to-Paid numerator. This reconciles to 9 and 19 on the verified live snapshot. |
| ARPAS | `revenue / purchases` | Correct for this no-trial price test; the verified snapshot reconciles to `$9.57` and `$8.59`. |
| CR unique view→purchase | `purchases / unique_views * 100` | The unique-view conversion rate, not Adapty's repeated-view CR. |

The old Funnel and Cohort sources are excluded because their install-cohort grain does not reconcile to the active test. A fixed repeated-views multiplier is also excluded because it would drift over time and become an opaque calibration workaround.

## Architecture

Create a focused `AdaptyAbExportClient` that owns Secret-Key authorization, rate limiting, retry behavior, request construction, strict response parsing, and derived metrics. The report module owns configuration mapping and Telegram formatting only.

The collector makes three sequential Analytics Export calls per variant:

1. `revenue`
2. `paywall_view_paid`
3. `refund_events`

Requests run below Adapty's two-requests-per-second limit. Transient `429` and `5xx` responses are retried with backoff. Authentication, HTTP, JSON, missing-field, negative-value, non-integral count, or inconsistent-result failures abort the whole A/B report; partial or mixed-snapshot messages are never sent.

The former A/B Dashboard client is removed from the A/B path. Dashboard credentials remain available only for the separate Apple Ads integration.

## Telegram format

The message uses Telegram HTML and contains no source, timestamp, latency note, or extra metrics:

```text
🧪 A/B Test: Test paywall prices. 4.99/29.99 vs 5.99/39.99
📱 App: Unfollowers: Follow & Unfollow

🅰️ A / New Paywall Old Prices
💵 Revenue: $86.11
📈 ARPAS: $9.57
👥 Unique paywall views: 570
💳 Purchases: 9
🔄 CR unique view→purchase: 1.58%

🅱️ B / New Paywall New Prices
💵 Revenue: $163.25
📈 ARPAS: $8.59
👥 Unique paywall views: 573
💳 Purchases: 19
🔄 CR unique view→purchase: 3.32%

🏆 Лидер по revenue: B (+$77.14)
```

Variant headings are bold in the actual Telegram HTML message.

## Configuration and security

The A/B report requires the existing app Secret API Key, test ID, start date, and two immutable paywall mappings. It no longer requires `ADAPTY_DASHBOARD_APP_ID` or `ADAPTY_DASHBOARD_TOKEN`.

Secrets remain in Railway variables. Tests, logs, preview output, commits, and documentation never contain credential values. Errors log only safe exception types and metric context.

## Verification and release gates

Before enabling production delivery:

1. Unit and contract tests pass, including an exact golden Telegram message.
2. A live preview built with the protected Railway Secret Key returns complete metrics for both variants.
3. Revenue, purchases, ARPAS, unique views, and unique CR are reconciled against the same Adapty Dashboard snapshot within the documented views-refresh lag.
4. The report remains disabled during the code deploy.
5. GitHub main and the Railway deployment point to the same verified commit.
6. Production A/B delivery is enabled only after Railway is healthy.
7. Exactly one one-shot report is sent to the configured general Telegram chat, and runtime logs confirm success without credential leakage.

