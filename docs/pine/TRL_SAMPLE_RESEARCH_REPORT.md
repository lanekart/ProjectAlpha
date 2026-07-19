# TRL Sample Research Report

## Evidence Status

This is a structural example only. It deliberately contains no fabricated
performance values and is not empirical evidence.

```text
TradingView Research Laboratory Report
Experiment ID: trl-example-unmeasured
Title: Example indicator ablation
Purpose: Demonstrate the report contract without claiming a result.
Alpha Baseline: trl-config-83c0bd90054c4f71
Treatment: unavailable until the configuration is frozen

Measured Comparison
Matched Cohorts: 0
Improved: 0
Unchanged: 0
Worse: 0
Insufficient: 0
Weighted Expectancy Improvement: unavailable
Weighted Drawdown Improvement: unavailable

Candidate Promotion
Decision: REJECT
Promote: NO
Failed Gates: MISSING_DEVELOPMENT, MISSING_VALIDATION, MISSING_HOLDOUT,
MISSING_COMPARABLE_METRICS, INSUFFICIENT_SYMBOL_DIVERSITY,
INSUFFICIENT_SECTOR_DIVERSITY, PARTITION_LEAKAGE
Reason: No observed, population-matched TradingView evidence is registered.
Next Stage: collect measured development evidence; do not promote.
PRODUCTION_INFLUENCE=false
```

## Required Measured Comparison

An actual comparison must contain paired Alpha baseline and treatment rows for
the same partition, symbol, sector, start date, and end date. For example, a
NIFTY 200 experiment requires one chart run per authoritative point-in-time
member per partition, followed by Alpha-side distribution aggregation.

The absence of a numeric delta is a rejection condition. It is never replaced
with a default, assumed return, or estimated promotion score.

