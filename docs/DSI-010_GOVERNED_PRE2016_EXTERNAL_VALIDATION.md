# DSI-010 — Governed 2005–2015 External-Era Validation

## Purpose

DSI-010 validates whether the frozen DSI-009 `STOP-STRUCTURAL-10D` research lead and Alpha's regime-aware strategy-selection framework generalise to an earlier Indian-market era.

The external period is fixed at:

```text
2005-01-01 through 2015-12-31
```

No session from 2016 onward is admitted.

## Two separate tests

### Test A — Frozen stop transport

Test A transports the latest accepted DSI-007 regime-to-strategy mapping into the external era. The strategy mapping, entry rules, targets, trailing exits, time exits, capital constraints, transaction costs, and liquidity assumptions remain frozen.

Two portfolios receive the same selected signal population:

- `PRE2016_FROZEN_INCUMBENT` — the incumbent initial stop;
- `PRE2016_STOP_STRUCTURAL_10D` — the frozen ten-session structural-support stop.

Only the initial stop differs. External results never influence the transported mapping or stop parameters.

### Test B — Independent-era walk-forward replication

Test B reruns the full governed DSI-007 strategy tournament inside 2005–2015. Training, validation, and test folds are created chronologically from the earlier data. Test B does not import the DSI-007 selected mapping from 2016–2025.

Test A and Test B are reported separately and are not counted as independent confirmations of the same hypothesis.

## Required inputs

The operator requires:

- the signed DSI-009 certificate;
- the signed DSI-007 certificate and support package;
- a Historical Truth DuckDB containing governed adjusted daily candles, identity intervals, membership intervals, corporate actions, price-basis intervals, and lineage for 2005–2015;
- the corresponding snapshot root;
- a governed total-return benchmark source, preferably Nifty 500 TRI.

Bulk market data, DuckDB files, and snapshot directories are not committed to GitHub.

## Data acquisition boundary

Official NSE historical-report and security-wise archives should be used through the repository's existing ingestion infrastructure. Acquisition must retain source provenance and hashes. Missing rows are never fabricated.

The build is complete independently of the local data population. Real-data certification remains blocked or partial when:

- adjusted candles do not cover the full period;
- point-in-time identity or membership is incomplete;
- corporate-action treatment is ambiguous;
- a governed TRI source is unavailable;
- the external trade population is below the pre-registered minimum.

## Frozen challenger contract

```text
candidate_id = STOP-STRUCTURAL-10D
family = STRUCTURAL_SUPPORT
lookback = 10 sessions
entry policy = unchanged
strategy selector = unchanged in Test A
portfolio policy = unchanged
cost and slippage models = unchanged
```

The engine validates this contract against the DSI-009 certificate and registered stop definition before loading external results.

## Interpretation

The following classifications are available:

- `CHALLENGER_BEATS_BENCHMARK`
- `CHALLENGER_BEATS_INCUMBENT_NOT_BENCHMARK`
- `EXTERNAL_VALIDATION_DIRECTIONALLY_SUPPORTED`
- `EXTERNAL_VALIDATION_MIXED`
- `EXTERNAL_VALIDATION_FAILED`
- `INSUFFICIENT_EXTERNAL_SAMPLE`

A positive result permits only extended forward paper validation. It does not activate a live stop policy.

## CLI surface

The dedicated module exposes:

```text
decision-superiority-pre2016-external-validation
decision-superiority-pre2016-external-validation-verify
```

The runner accepts explicit certificate, database, snapshot, benchmark, date, and output arguments. The date protocol rejects any overlap with 2016 or later.

## Deterministic outputs

The package writes one certificate, one executive report, and deterministic ledgers covering:

- frozen protocol and source contracts;
- market, universe, corporate-action, and benchmark coverage;
- frozen mapping;
- incumbent and challenger signals/trades;
- stop differences;
- external equity curves;
- independent-era folds and selections;
- portfolio, rolling, calendar, regime, risk, and benchmark-relative results;
- robustness, concentration, reconciliation, and non-vacuity probes.

Every support artifact is SHA-256 bound into the certificate. The validator rejects tampering, unsafe paths, and machine-local path leakage.

## Governance

All policy and production influence flags remain false:

```text
STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false
LIVE_STOP_POLICY_ENABLED=false
LIVE_STRATEGY_SELECTION_ENABLED=false
LIVE_SCORING_ENABLED=false
PRODUCTION_SIGNAL_PUBLICATION_ENABLED=false
PRODUCTION_PORTFOLIO_INFLUENCE=false
THRESHOLD_CHANGE_PERMITTED=false
APPROVAL_POLICY_CHANGE_PERMITTED=false
PORTFOLIO_POLICY_CHANGE_PERMITTED=false
EXECUTION_POLICY_CHANGE_PERMITTED=false
ECONOMIC_SUPERIORITY_CLAIMED=false
CAUSAL_CLAIM_PERMITTED=false
DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false
PRODUCTION_INFLUENCE=false
```

The 2005–2015 period may not be reused for challenger tuning after its result is observed.
