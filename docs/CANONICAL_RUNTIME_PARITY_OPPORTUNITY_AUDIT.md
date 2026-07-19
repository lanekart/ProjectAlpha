# Canonical Runtime Integrity, TradingView Parity & Opportunity Audit

## Purpose

This diagnostic explains why TradingView can produce technical trades while
`ALPHA_CANONICAL_v1.0` produces no institutional approvals. It combines:

1. canonical runtime-failure reconstruction and repaired replay;
2. exact TradingView trade import and progressive Pine/Python matching;
3. deterministic major-opportunity construction and funnel attribution.

It does not optimize Alpha. It does not change recommendation weights,
thresholds, setup rules, entry timing, trade plans, approval gates, allocation,
or production policy.

## Frozen Policy

Every report persists a policy manifest containing the source commit, scoring
weights, verdict thresholds, setup and engine versions, approval-policy
version, outcome definition, dataset version, and provider label. Only
`ALPHA_CANONICAL_v1.0` and `LEGACY_DATASET` are accepted by the CLI.

The legacy warehouse is labelled `PROVISIONAL`. TradingView is always a
secondary validator.

## Runtime Repair Boundary

ACU-1 found a unit-contract failure at the recommendation-to-allocation
adapter. Legacy one-session range volatility can exceed 100%. The recommendation
engine retained that evidence as a fractional expected drawdown above `1.0`,
while `AllocationCandidate` correctly requires a bounded fractional value in
`[0, 1]`.

The repair exists only in `CanonicalAuditInputSet`. It creates a bounded copy
for the allocation handoff. It does not replace or edit the recommendation,
score, verdict, setup, or expected-value evidence. The integrity audit bypasses
that wrapper to reproduce the original exception and retains the before-state
as immutable evidence.

A second diagnostic-adapter defect passed malformed legacy bars whose close sat
outside the reported high/low range. `CanonicalAuditInputBuilder` now excludes
only those invalid bars before canonical analysis and reduces the resulting data
completeness accordingly. It does not repair, substitute, or synthesize prices,
and the pre-repair path remains available to reproduce the frozen failures.

## Runtime Failure Evidence

Each affected candidate records the date, symbol, pipeline stage, exception,
source location, sanitized input state, missing fields, provider state,
dataset version, deterministic reproduction status, and root-cause hash.

Grouping is by normalized category, stage, exception, message, and source file.
This separates repeated implementation defects from unique failures.

## TradingView Evidence Hierarchy

Evidence is classified as:

- `CSV_TRADE_LEVEL`: exported Strategy Tester trade rows;
- `CSV_SUMMARY`: summary-level experiment evidence;
- `SCREENSHOT_DERIVED`: manually attested evidence with lower standing.

Screenshot-derived evidence is never upgraded to trade-level evidence. A parity
rate is unavailable when no exact trade CSV has been imported.

Matching proceeds by symbol, entry date, nearby entry bar/date, setup family,
strategy family, entry tolerance, stop tolerance, and target tolerance. Each
trade receives one typed classification. A canonical rejection remains a
rejection even when the technical setup is semantically similar.

## Major Opportunity Definitions

The initial definitions are:

- at least 20% within 60 sessions;
- at least 30% within 90 sessions;
- at least 50% within 180 sessions.

Forward highs are point-in-time bounded. Overlapping qualifying windows for the
same symbol and definition are merged into one cluster. The representative is
the row with the largest forward return, with earliest date as the deterministic
tie-breaker. MFE-like forward return, time to peak, adverse excursion before the
peak, volume expansion, and 20-session trend context are retained.

Event construction does not assert that a large price increase was a valid or
tradable setup. Coverage classification separately asks whether Alpha created,
scored, timed, planned, approved, and entered a comparable candidate.
Unreconciled moves of at least 1,000% are classified `DATA_BLOCKED` until
corporate-action and identity continuity can be validated.

## Coverage and Zero-Trade Attribution

Opportunity coverage uses the mutually exclusive states `CAPTURED`,
`PARTIALLY_CAPTURED`, `REJECTED`, `MISSED`, `UNSCORABLE`, `RUNTIME_BLOCKED`, and
`DATA_BLOCKED`.

Every symbol without an institutional trade receives one primary zero-trade
reason. The reason follows the funnel and does not default to approval-policy
blame.

Mandatory case studies resolve dataset aliases for Kalyan Jewellers and PC
Jeweller, plus Reliance, TCS, HDFC Bank, LT, and Tata Steel. If the frozen ACU
artifact lacks component-level scores, the case study says so rather than
recomputing them after the event.

## Commands

```text
poetry run python -m alpha integrity-audit runtime
poetry run python -m alpha integrity-audit runtime --replay
poetry run python -m alpha integrity-audit pine-import --directory PATH
poetry run python -m alpha integrity-audit parity
poetry run python -m alpha integrity-audit opportunities
poetry run python -m alpha integrity-audit missed
poetry run python -m alpha integrity-audit zero-trades
poetry run python -m alpha integrity-audit case-study --symbol KALYANKJIL
poetry run python -m alpha integrity-audit report
```

Use `--before-acu` to retain the original ACU artifact and `--after-acu` for the
post-repair rerun. The report command supports date, symbol, event definition,
policy version, dataset version, JSON, CSV, and output controls.

## Outputs

The audit writes the required runtime, parity, opportunity, missed-opportunity,
zero-trade, case-study, policy-manifest, JSON, CSV, and executive-report
artifacts under `.alpha/canonical_integrity/ALPHA_CANONICAL_v1.0` by default.

## Research Governance

The IRD plugin exposes runtime failure rate, Pine parity rate,
major-opportunity capture and partial-capture rates, miss rate, and
runtime-blocked count. Metrics preserve source, definition, population, and
version. A completed immutable research-registry record is created by the full
report command.

## Guardrails

```text
PRODUCTION_INFLUENCE=false
NO_POLICY_RELAXATION=true
NO_WEIGHT_CHANGES=true
NO_THRESHOLD_CHANGES=true
NO_STRATEGY_CHANGES=true
NO_APPROVAL_CHANGES=true
DIAGNOSTIC_REPAIRS_ONLY=true
TRADINGVIEW_IS_SECONDARY_VALIDATOR=true
LEGACY_DATA_IS_PROVISIONAL=true
```
