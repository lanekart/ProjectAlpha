# Institutional Gate Truth Audit (IGTA v1.0)

IGTA is a diagnostic-only audit of the institutional gate frozen by
`ALPHA_BASELINE_v1.0`. It answers whether rejected `BUY` and `STRONG_BUY`
signals subsequently protected capital or suppressed genuine edge. It cannot
change a gate, score, weight, feature, threshold, recommendation, allocation,
or production policy.

## Frozen Inputs

The audit requires these immutable evidence sources:

- CABR `manifest.json` and `approval_statistics.csv`.
- ACU `candidate_rankings.csv` and `gate_attribution.csv`.
- The exact legacy warehouse checksum recorded by CABR.

Before evaluation, IGTA verifies the CABR approval artifact checksum, compares
the warehouse checksum to the frozen manifest, and reconciles CABR and ACU
candidate scores and primary rejection reasons. Any mismatch fails closed.

The CABR artifact did not persist complete recommendation component scores.
IGTA therefore records `UNAVAILABLE_IN_CABR_BASELINE` and uses only the frozen
gate categories for component attribution. It does not recalculate historical
component scores with newer code.

## Outcome Rules

Only sessions after the recommendation date are eligible. Entry must trigger
within the CABR five-session validity window. A gap above the trigger fills at
the opening price; otherwise the frozen trigger price is used.

Every rejection receives independent 20-, 60-, and 120-session outcomes plus
an outcome using the original expected holding period. Each outcome records:

- entry and exit state;
- target and stop touches;
- first-event ordering;
- MFE and MAE;
- gross and after-cost return;
- realized R;
- data completeness; and
- same-bar ambiguity.

When a stop and target occur in the same bar, the stop wins. Transaction costs
and slippage are read from the CABR manifest and never silently changed.

## Classification

- `CORRECT_REJECTION`: stop occurs before target, or the fully observed planned
  time exit loses money after frozen costs.
- `FALSE_REJECTION`: target occurs before stop, or the fully observed planned
  time exit makes money after frozen costs.
- `MARGINAL`: the entry never triggers inside a fully observed validity window,
  or the planned result is exactly breakeven.
- `DATA_UNCERTAIN`: the trade plan is invalid, the required outcome window is
  incomplete, or available data cannot establish a terminal result.

These definitions are event-based. No return cutoff was fitted to outcomes.

## Counterfactual

The gate-off counterfactual includes every rejected signal whose frozen entry
triggered. Every signal is an independent logical trade. Daily strategy return
is the equal-weight mean return of all active logical trades. There is no
ranking, candidate selection, position limit, capital preference, or optimized
exit. This is a diagnostic comparison, not Alpha and not a deployable portfolio.

The counterfactual reports CAGR, maximum drawdown, win rate, payoff ratio,
expectancy, Sharpe, and Sortino. Open boundary trades remain unresolved and are
not treated as completed wins or losses.

## Economic Attribution

Opportunity value lost and capital protection gained use an equal notional of:

`CABR initial capital / total rejected BUY population`

Positive completed outcomes contribute to opportunity value lost. Negative
completed outcomes contribute to capital protection gained. Reason statistics
are emitted twice:

- `PRIMARY`: mutually exclusive CABR primary rejection cohorts.
- `ALL_FAILURES`: overlapping statistics for every gate code attached to a
  rejected candidate.

## Confidence

Conclusion confidence considers frozen sample support and outcome maturity.
The provisional legacy warehouse and absence of a separately reserved holdout
cap IGTA v1.0 at `MEDIUM`, even with a large sample. Historical identity and
corporate-action limitations remain explicit.

## Commands

```text
poetry run python -m alpha gate audit
poetry run python -m alpha gate rejected
poetry run python -m alpha gate effectiveness
poetry run python -m alpha gate counterfactual
poetry run python -m alpha gate report
```

`gate audit` writes deterministic artifacts under
`.alpha/gate_truth/IGTA_v1.0`. Repeated runs against the same frozen evidence
are idempotent. A different CABR manifest cannot overwrite the directory.

## Artifacts

- `rejected_population.csv`
- `rejection_classification.csv`
- `gate_effectiveness.csv`
- `reason_statistics.csv`
- `counterfactual_portfolio.csv`
- `counterfactual_trades.csv`
- `counterfactual_statistics.csv`
- `component_attribution.csv`
- `false_rejections.csv`
- `executive_report.md`
- `manifest.json`

## Isolation

The manifest permanently asserts:

```text
PRODUCTION_INFLUENCE=false
NO_GATE_CHANGES=true
NO_WEIGHT_CHANGES=true
NO_THRESHOLD_CHANGES=true
NO_FEATURE_CHANGES=true
```
