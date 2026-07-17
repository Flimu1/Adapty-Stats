# Adapty A/B Report Reliability Implementation Plan

> **Execution workflow:** Follow `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before any completion claim.

**Goal:** Replace paywall-wide A/B calculations with validated experiment-scoped Adapty metrics, expose snapshot latency, prevent secret leakage, deploy the fix to Railway production, and send one verified A/B report to the configured general Telegram chat.

**Architecture:** A focused dashboard API client owns authentication, experiment identity validation, and response parsing. `ab_test_report.py` becomes a formatter/orchestrator over that client and never calls generic paywall analytics. A root logging filter protects all libraries from leaking credentials. A one-shot CLI command builds and sends only the A/B report and returns a meaningful exit code.

**Stack:** Python 3, requests, unittest/mock, Railway CLI, Telegram Bot API.

---

## Task 1: Capture and lock the Adapty experiment contract

**Files:**

- Modify: `.env.example`
- Modify: `config.py`
- Test: `tests/test_config.py`
- Create: `tests/test_adapty_ab_dashboard.py`

1. Complete the existing Google passkey challenge and sign in to Adapty using the persistent Playwright profile.
2. Open the target A/B test and capture the metadata and metrics JSON returned by the dashboard for the same snapshot.
3. Record the immutable A/B test ID and identify the exact response paths for variant letter, paywall ID/name, revenue, revenue per 1k users, views, purchases, and conversion.
4. Add failing configuration tests requiring `AB_TEST_ID`, `ADAPTY_DASHBOARD_APP_ID`, and `ADAPTY_DASHBOARD_TOKEN` when A/B reporting is enabled.
5. Run the focused tests and confirm they fail for the missing fields.
6. Add the configuration accessors and documented example variables.
7. Run focused tests and confirm they pass.
8. Commit the configuration contract.

## Task 2: Build an experiment-scoped, fail-closed dashboard client

**Files:**

- Create: `adapty_ab_dashboard.py`
- Create/Modify: `tests/test_adapty_ab_dashboard.py`

1. Add a representative sanitized metadata/metrics payload from the live dashboard to tests.
2. Add failing tests for dashboard authorization normalization, exact experiment endpoints, successful variant parsing, A/B ordering, and required metrics.
3. Add failing tests for 401, malformed JSON, unknown response shape, missing variants, duplicate paywalls, wrong test name/ID, and reversed configured mapping.
4. Confirm the focused tests fail before implementation.
5. Implement a small requests-based client with explicit timeouts and typed result dataclasses.
6. Raise a domain-specific exception on every authentication, identity, or data-contract failure; never return partial metrics.
7. Ensure log messages contain status/type/context but no raw credential or response body.
8. Run focused tests and confirm all pass.
9. Commit the client and tests.

## Task 3: Replace the A/B report data path and make latency explicit

**Files:**

- Modify: `ab_test_report.py`
- Rewrite/Modify: `tests/test_ab_test_report.py`

1. Add failing tests proving `fetch_ab_test_metrics` delegates only to the dashboard client and cannot call generic Analytics Export helpers.
2. Add failing formatter tests for the verified A/B mapping, dashboard-sourced metrics, source marker, collection timestamp/timezone, views latency note, and leader delta.
3. Add a failing test that a client/domain error propagates so delivery fails closed.
4. Confirm focused tests fail.
5. Remove the generic revenue/cohort/funnel A/B request path and obsolete parsers.
6. Map dashboard results into the report dataclass and render the validated report.
7. Run focused tests, then the full suite.
8. Commit the A/B report replacement.

## Task 4: Redact secrets across application and library logs

**Files:**

- Create: `safe_logging.py`
- Create: `tests/test_safe_logging.py`
- Modify: `main.py`
- Modify: `telegram_bot.py`
- Modify: `telegram_sender.py`
- Modify: `tests/test_telegram_sender.py`

1. Add failing tests that exercise direct token text, `/bot<TOKEN>/` URLs, tuple-formatted logging arguments, and urllib3-style retry messages.
2. Add failing tests that Telegram request failures log only safe exception types/status context.
3. Confirm focused tests fail.
4. Implement a root-handler logging filter and install it immediately after `logging.basicConfig`.
5. Replace raw exception logging in Telegram request paths with safe structured context.
6. Run focused tests and the full suite.
7. Commit the security fix.

## Task 5: Add an auditable one-shot A/B delivery command

**Files:**

- Modify: `telegram_sender.py`
- Modify: `main.py`
- Modify: `tests/test_telegram_sender.py`
- Create/Modify: `tests/test_main.py`

1. Add failing tests for `send_ab_report_once`: it sends exactly one built A/B message, returns false when disabled/empty, and does not send on build error.
2. Add a failing CLI test for `--send-ab-report` returning non-zero when build or delivery fails.
3. Confirm focused tests fail.
4. Implement the one-shot sender and CLI flag without invoking the main report or Apple Ads report.
5. Run focused tests and the full suite.
6. Commit the delivery command.

## Task 6: Production configuration, credential rotation, and live reconciliation

**Files:**

- Modify: Railway production variables only
- Modify: Adapty/Google browser session only
- Modify: Telegram BotFather token only

1. Run Railway CLI authentication/status preflight and record project, environment, and service IDs.
2. Update `AB_TEST_ID`, correct A/B paywall mapping, and replace the stale dashboard credential in Railway without exposing values in output.
3. Rotate the Telegram bot token in BotFather, update `TELEGRAM_BOT_TOKEN` in Railway, and invalidate the exposed token.
4. Run a live dry build with production variables but no Telegram send.
5. Query the Adapty dashboard endpoint at the same snapshot and compare every reported field and variant identity.
6. If any field differs, stop and correct the parser/configuration before deployment.

## Task 7: Integrate, deploy, verify, and send

**Files:**

- Merge commits from `codex/adapty-ab-reliability` into `main`
- Push `main` to `origin`

1. Read and follow `superpowers:requesting-code-review`, perform the review, and address actionable findings.
2. Read and follow `superpowers:verification-before-completion`; run the full test suite from a clean state.
3. Merge the reviewed branch into `main` without discarding unrelated work and push to GitHub.
4. Wait for Railway to deploy the pushed commit; require a successful deployment and healthy worker logs.
5. Verify production logs contain neither Telegram token nor `/bot<token>/` URL after controlled failure-safe requests.
6. Run a fresh production dry build and a same-snapshot Adapty reconciliation.
7. Execute `python main.py --send-ab-report` in the deployed Railway container exactly once.
8. Require command success and verify the message targeted the configured production group/topic.
9. Read and follow `superpowers:finishing-a-development-branch` for cleanup and final handoff.

## Done when

- All tests pass from the isolated worktree and integrated `main`.
- A/B values and mapping match Adapty at the same snapshot.
- Incorrect or unauthenticated A/B data cannot be sent.
- The stale Adapty credential and exposed Telegram token are replaced.
- Railway runs the deployed commit successfully with secret-safe logs.
- Exactly one verified A/B report is delivered to the production general Telegram chat/topic.
