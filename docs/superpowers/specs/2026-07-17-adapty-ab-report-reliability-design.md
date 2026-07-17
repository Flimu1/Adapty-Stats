# Adapty A/B Report Reliability Design

**Date:** 2026-07-17

## Goal

Make the Telegram A/B report use the same experiment-scoped data as Adapty's A/B Test Details screen, prevent mislabeled variants or silently incorrect fallback data, make update latency visible, and prevent Telegram credentials from appearing in logs.

## Confirmed failure modes

1. The current report filters the generic Analytics Export API only by `paywall_id`. A paywall can also be used outside the selected experiment, so its revenue and funnel counts are not experiment-scoped. This is why the old-price paywall was materially overstated while the new-price paywall happened to look close.
2. Production variant configuration was reversed relative to Adapty: the dashboard defines A as new prices and B as old prices.
3. Adapty updates views periodically while most financial metrics update continuously. The report did not identify its snapshot time or explain this expected lag.
4. The stored dashboard credential is invalid. The bot therefore has no valid path to the experiment-scoped endpoint today.
5. Telegram Bot API tokens are embedded in request URLs. Request exceptions and urllib3 retry messages can include those URLs, and a production token has already appeared in Railway logs.

## Source of truth

The production report will use Adapty's experiment-specific dashboard API, not generic paywall analytics:

- experiment metadata: `/api/v1/portal/{app_id}/in-apps/ab-tests/{ab_test_id}`
- A/B summary/detail metrics: `/api/v1/portal/{app_id}/analytics/ab-tests/...`

These are the endpoints used by Adapty's current web dashboard. The bot will use a dashboard credential stored only in Railway variables. Browser automation is allowed for diagnosis and credential renewal, but it is not part of the production reporting path.

The generic Analytics Export API will remain available for the main business report, but it will no longer be used as a fallback for an A/B report. A paywall-level fallback would produce plausible-looking but semantically wrong data.

## Experiment and variant identity

Production will store the immutable Adapty A/B test ID. On every report build, the bot will validate:

- the returned test ID and configured test name;
- exactly two variants;
- the paywall IDs and names associated with variants A and B;
- A = `New Paywall New Prices` and B = `New Paywall Old Prices` for the current test.

The variant letter comes from the experiment response/order, not from an independently maintained Telegram label. Any mismatch is a hard error and suppresses the A/B report.

## Data flow and failure behavior

1. Load the A/B test ID, dashboard app ID, and dashboard credential from production configuration.
2. Fetch experiment metadata and validate the expected test and variants.
3. Fetch the experiment-scoped metrics used by Adapty.
4. Parse and validate required values before formatting.
5. Render the report with an explicit Adapty source marker and snapshot timestamp/timezone.
6. Send only after the build succeeds completely.

Authentication errors, response-shape changes, missing variants, missing required metrics, or identity mismatches fail closed. The scheduler logs a safe diagnostic and continues other reports; it never substitutes paywall-wide numbers under the A/B test heading.

## Metric semantics and latency

The Telegram labels will mirror Adapty's A/B definitions. Revenue is experiment-attributed revenue including purchases and renewals, net of refunds and before store commission. Conversion is calculated only from experiment-scoped purchases and views. Views are marked as periodically updated because Adapty documents that views can lag other metrics.

The message includes the collection time so a later screenshot is not mistaken for the same snapshot. No artificial cache is added in the bot.

## Credential and logging security

All root logging handlers will redact configured secrets and Telegram bot URL path tokens before formatting any record. Telegram request exceptions will log method, exception type, and safe status information instead of raw exception URLs. Tests will cover both direct messages and urllib3-style argument formatting.

Because the existing Telegram token has appeared in historical logs, code redaction prevents further disclosure but does not invalidate the exposed token. The token must be rotated through BotFather, updated in Railway, and verified with the deployed worker before the issue is considered fully closed.

## Production delivery

A dedicated one-shot command will build and send only the A/B report. It will be executed in the deployed Railway container after:

- all automated tests pass;
- a live dry run matches the Adapty A/B endpoint at the same snapshot;
- the production deployment is healthy;
- the refreshed Adapty credential and rotated Telegram credential are active.

The command exits non-zero if collection or delivery fails, making the final send auditable.

## Alternatives rejected

- **Paywall-only analytics with a placement field:** the public endpoint silently ignored both valid and deliberately invalid placement values in live tests, so this cannot be trusted.
- **Scraping the dashboard in production:** fragile, difficult to monitor, and dependent on interactive browser sessions.
- **Continue on stale or partial data:** risks another authoritative-looking but incorrect group message.

## Definition of done

- A live dry run reports the same variant mapping and values as Adapty for the same snapshot.
- Generic paywall aggregation is not reachable from the A/B reporting path.
- Invalid credentials or mismatched variants suppress the report with safe diagnostics.
- Telegram secrets are redacted in unit tests and Railway logs.
- The Telegram token is rotated and the worker remains healthy.
- The fixed report is sent once to the configured production general chat and topic.
