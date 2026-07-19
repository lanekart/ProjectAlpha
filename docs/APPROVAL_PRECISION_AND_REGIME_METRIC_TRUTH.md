# Approval Precision and Regime Metric Truth Audit

## Purpose

This diagnostic-only audit establishes explicit contracts for approval precision
and validates the market-regime metric consumed by the Institutional Research
Director (IRD).

`PRODUCTION_INFLUENCE=false`

The audit does not modify recommendation, approval, timing, ranking, learning,
replay, allocation, risk, execution, live-data, or trading policy.

## Commands

```text
poetry run python -m alpha research approval-precision-truth
poetry run python -m alpha research approval-population-reconciliation
poetry run python -m alpha research regime-metric-truth
poetry run python -m alpha research metric-truth-summary
```

Every command supports `--format text|json|csv`. JSON and CSV can be written
atomically with `--output PATH`.

## Approval Contracts

The audit keeps these concepts separate:

- `RAW_APPROVAL`: persisted `approved_for_deployment` decision.
- `STRICT_INSTITUTIONAL_APPROVAL`: the complete
  `is_deployment_approved(record)` predicate.
- `RECOMMENDATION_BUY`: BUY or STRONG_BUY recommendation verdict.
- `ACTIONABLE_CANDIDATE`: current entry-timing assessment is actionable.
- `ENTRY_TIMING_APPROVAL`: persisted raw approval used by timing replay.
- `GATEKEEPER_APPROVAL`: persisted gatekeeper acceptance result.
- `LEGACY_LONG_TRADE_PERMISSION`: legacy long-side permission flag.

The canonical raw precision contract is:

```text
numerator   = raw approvals with gross primary-window entry return > 0
denominator = raw approvals with a completed primary outcome and entry return
horizon     = first usable 20d, 10d, 5d, 3d, 1d, or 60d outcome
missing     = excluded from the denominator
duplicates  = duplicate candidate IDs invalidate the audit
costs       = not included; this is gross outcome precision
version     = approval-precision-contract-v1
```

Strict institutional precision has its own denominator. With zero strict
approvals it is `NOT_ESTIMABLE`, never `0%`.

## Reconciled Evidence

The current repository evidence produces:

- Earlier raw approval slice: 13 wins among 41 completed approvals, 31.71%.
- Current raw approval population: 24 wins among 70 completed approvals, 34.29%.
- Population addition: 29 completed approvals, comprising 11 wins and 18
  non-wins.
- Shared outcome classification changes: 0.
- Horizon or success-definition changes: 0.
- Duplicate or overwritten records: 0.
- Unexplained precision remainder: 0.
- Current raw 95% Wilson interval: 24.25% to 45.96%.

The earlier number is reconstructed from completed raw approvals through
2016-12-13 because a persisted report manifest for that earlier run is not
available. The command labels this origin explicitly.

## Strict Gate Attribution

The audit evaluates the strict predicate in source order and reports both:

- mutually exclusive first-failing gate counts; and
- overlapping failures across all gates and the extended approval diagnostic.

The current zero-approval result is classified
`VALID_BUT_OVERRESTRICTIVE_POLICY`: implementation and predicate agree, while
completed profitable candidates are rejected. No threshold is changed by this
classification.

## Regime Metric Finding

The native 1.29% balanced-accuracy arithmetic is reproducible as 20 correct
bearish mappings among 1,546 candidate records. It is not a valid predictive
quality estimate.

All benchmark-return inputs are absent. The diagnostic fallback uses normalized
price/trend component values between 0.4323 and 0.9320, but compares them with
35 and 75 thresholds. This scale mismatch makes every synthetic reference label
bearish. Twenty NEGATIVE predictions match; 1,526 NEUTRAL predictions do not.

The result is classified `SCALE_OR_RENDERING_DEFECT`, specifically a reference
scale defect. Fraction-to-percentage rendering is correct. IRD now exposes this
metric as `INVALID` and removes it from measured bottleneck prioritization. The
underlying regime audit and all production behavior remain unchanged.

## IRD Metric Safety

Every adapter metric preserves source, definition, population, version, unit,
availability, and numerator/denominator where the metric is a direct fraction.

Guardrails enforce that:

- ratio values remain fractions in the range zero to one;
- unavailable, `NOT_ESTIMABLE`, `INVALID`, and numeric zero remain distinct;
- numerator and denominator reconstruct direct fraction metrics;
- definition-incompatible metrics cannot be compared as an experiment delta;
- diagnostics containing invalid metrics cannot become measured bottlenecks;
- the quarantined regime metric cannot drive roadmap priority.

## Research Registry

Running any metric-truth command idempotently records the completed experiment
`approval-regime-metric-truth-audit-v1-<data-as-of>`. It contains baseline and
reconciled metrics, evidence sources, findings, confidence, decision, lessons
learned, and `production_influence=false`.

## Constraints

- Diagnostic evidence does not authorize paper or live deployment.
- Raw approval precision is not strict institutional approval precision.
- Gross outcome precision is not net profitability or expectancy.
- The native regime metric must not be used until reference labels are repaired
  and independently revalidated.
- This milestone adds no indicators, thresholds, scores, or production wiring.
