# DSI-008 Governed Performance Improvement

## Purpose

DSI-008 completes the governed total-return benchmark, decomposes the frozen
DSI-007 result, tests bounded one-factor mechanism challengers, and measures
whether selective signal tiers improve wealth as well as accuracy.

This subsystem is research-only. It cannot publish signals, alter scoring,
change portfolio policy, activate a strategy, or place an order.

## Source Boundary

The engine requires:

1. A valid DSI-007 certificate with all hash-bound support artifacts.
2. A Nifty total-return series with a sibling `.provenance.json` file.
3. Optionally, the immutable historical-truth database for forward-path and
   MFE/MAE diagnostics.

The benchmark contract records index identity, total-return semantics, source,
source version, SHA-256, currency, dividend treatment, adjustment treatment,
dates, duplicate and nonpositive-value checks, and return calculation.

A price index is never substituted for TRI. Missing or invalid provenance fails
closed.

## Anti-Overfitting Contract

DSI-007 remains the frozen incumbent. DSI-008 does not tune against the
aggregate DSI-007 outer-period result.

All challengers:

- have stable IDs;
- change exactly one field;
- are registered before evaluation;
- retain unchanged fields explicitly;
- preserve failed outcomes;
- never use outer-fold results to define the same fold.

The current warehouse ends in 2025. No unused 2026 holdout exists, so DSI-008
does not claim a renewed untouched holdout. Results remain descriptive unless
future forward evidence supplies that boundary.

## Outcome Definitions

Accuracy is reported separately for:

- target before stop at 1R, 2R, and 3R;
- positive returns at 5, 10, 20, and 60 sessions;
- benchmark outperformance at 20 and 60 sessions;
- positive realised trade return;
- positive realised R.

Unavailable outcomes remain empty/unknown.

## Signal Tiers

`ALPHA_STANDARD` retains the incumbent population.

`ALPHA_HIGH_CONVICTION` uses the prior train/validation 75th percentile of
signal strength.

`ALPHA_ELITE` uses the prior train/validation 90th percentile. An observed 75%
accuracy is not accepted without the governed minimum completed sample, a
meaningful Wilson interval, positive expectancy, positive wealth contribution,
fold stability, and acceptable concentration.

No tier is enabled in production.

## Artifacts and Certification

The engine writes 25 deterministic CSV ledgers, one executive report, and one
certificate. The certificate binds every support artifact by SHA-256 and
validates governance flags, source hashes, report integrity, and the absence of
automatic promotion.

## CLI

```bash
poetry run python -m alpha benchmark \
  decision-superiority-performance-improvement \
  --dsi007-certificate <PATH> \
  --tri-benchmark <PATH> \
  --database <PATH> \
  --output <PATH>
```

Verify:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-performance-improvement-verify \
  --certificate <PATH> \
  --require-ready
```

## Known Limitations

- DSI-007 produced only 56 incumbent out-of-sample trades.
- Several confidence inputs requested by the research design are not present
  in the frozen DSI-007 ledgers and remain unknown.
- Trade filtering is an offline challenger diagnostic, not a complete
  replacement portfolio replay.
- Execution-policy stresses requiring a new replay are marked unavailable and
  are not fabricated.
- No genuinely unused 2026 final holdout exists in the governed warehouse.

## Governance

`PRODUCTION_INFLUENCE=false`

All threshold, gate-order, approval, portfolio, execution, live selection,
signal publication, recommendation, learning mutation, and automatic
promotion flags remain false.

