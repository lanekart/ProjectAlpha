# HTR-010B1 Adjustment Validation and Replay Admission

## Purpose

HTR-010B1 validates factor and price-basis risks identified by HTR-010B and produces a candidate-independent identity-date admission contract for future adjusted replay.

It does not modify the active replay path, strategy logic, scores, approvals, stop losses, targets, portfolio policy, execution, canonical raw candles, or production behaviour.

`PRODUCTION_INFLUENCE=false`

## Inputs

The engine consumes the deterministic HTR-010B artifacts:

- canonical corporate-action events;
- adjustment factors;
- price-continuity diagnostics;
- price-basis intervals;
- adjusted-candle summaries;
- identity coverage;
- identity transitions.

No network access is required. Raw OHLCV remains immutable.

## Factor validation

Every `FACTOR_LIKELY_INCORRECT` continuity record becomes a deterministic validation case. Classification distinguishes:

- a correct factor followed by a genuine market gap;
- thin or delayed trading;
- event-date offsets;
- multiple simultaneous actions;
- series-applicability errors;
- non-multiplicative reorganisations;
- incomplete rights terms;
- conflicting official evidence;
- insufficient evidence;
- unresolved cases.

A residual adjusted gap alone does not prove the factor is wrong.

## Unknown factors

Unknown factors are never replaced with `1`.

Each event receives a replay impact such as:

- no technical adjustment required;
- raw-safe post-event interval;
- segment history at the event boundary;
- require a certified factor;
- identity transition is non-comparable;
- total-return-only impact;
- quarantine interval.

## Mixed price basis

Every mixed-basis identity is resolved into one explicit state:

- fully adjusted and certified;
- adjusted with a segmented uncertified interval;
- raw-only certified intervals;
- identity-transition segmentation;
- repaired implementation defect;
- quarantined mixed basis;
- unresolved.

No admitted replay interval may silently contain mixed price basis.

## Replay admission states

Every Tier A identity receives a versioned replay-admission interval. States include:

- adjusted replay certified;
- adjusted replay certified with tradability limitation;
- raw replay certified with no action exposure;
- raw replay certified after an event segment;
- segment boundary required;
- identity transition non-comparable;
- factor unknown or ambiguous quarantine;
- mixed-basis quarantine;
- conflicting or insufficient evidence quarantine;
- unresolved.

The contract records admitted and prohibited price views, event boundaries, factor states, and production influence.

## Indicator lookback safety

The audit computes reset-aware safety for 14, 20, 50, and 200-session lookbacks. A segmented or non-comparable boundary resets indicator eligibility. Quarantined intervals remain unavailable.

The current implementation uses a conservative calendar-date lower bound for exported diagnostics; future replay integration must calculate exact trading-session offsets from the certified session calendar.

## Point-in-time transformation contract

### Research continuity view

A research view may use actions effective by the chosen research cutoff to create a comparable historical series. Event knowledge itself is not available as a predictive feature before its historical publication time.

### Rolling as-of replay view

At replay date `t`, only actions effective on or before `t` may alter the transformation. The replay must pin immutable evidence and factor versions.

### Event knowledge

Announcements and filings may influence features only after their historical availability timestamp.

### Reproducibility

Raw candles remain immutable. Derived transformations are versioned and lineage-backed. Candidate IDs must remain stable across instrumentation-only changes.

## CLI

```bash
poetry run python -m alpha historical-truth adjustment-replay-admission-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --htr010a3-output artifacts/htr010a3_tier_a_foundation_readiness \
  --htr010b-output artifacts/htr010b_complete_corporate_action_dataset \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1_adjustment_replay_admission
```

Diagnostic filters do not alter certification.

## Artifacts

The exporter writes deterministic JSON, CSV, and Markdown reports covering:

- quarantine census and economic weight;
- factor-validation cases and outcomes;
- event boundaries and multiple-action cases;
- series applicability;
- unknown-factor impact;
- mixed-basis resolution;
- adjusted-row audit;
- replay-admission intervals;
- indicator-lookback safety;
- transformation contract;
- coverage matrix;
- readiness and rejected evidence.

## Governance

- candidate-independent;
- zero full benchmark replays;
- no symbol-only joins;
- no unknown factor applied as one;
- no silent mixed basis;
- no canonical-candle mutation;
- no future-event leakage;
- no strategy, score, approval, stop-loss, target, portfolio, execution, or production change;
- `PRODUCTION_INFLUENCE=false`.
