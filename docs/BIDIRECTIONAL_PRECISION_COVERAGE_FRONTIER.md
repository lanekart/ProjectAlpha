# Bidirectional Precision-Coverage Frontier

This milestone is diagnostic and research-only. It does not alter production
recommendation verdicts, approval gates, allocation, execution, live providers,
portfolio policy, or entry timing behavior.

`PRODUCTION_INFLUENCE=false`

## Signal Labels

- `BUY_DIRECTIONAL`: the future outcome satisfies the configured positive
  directional condition before breaching the adverse-risk boundary.
- `SELL_DIRECTIONAL`: the future outcome satisfies the configured negative
  directional condition before breaching the adverse-risk boundary in the
  opposite direction.
- `NEUTRAL`: neither directional condition is satisfied.
- `UNAVAILABLE`: the outcome cannot be evaluated honestly.

`SELL_DIRECTIONAL` is not the same as exiting an existing long position,
reducing allocation, opening a short position, or executing a risk stop.

## Outcome Families

Alpha now supports research labels for:

- terminal return outcomes;
- barrier-first outcomes;
- risk-adjusted outcomes;
- tradeability outcomes.

The frontier report compares policy behavior under an explicit definition
instead of choosing the label that gives the best precision.

## Walk-Forward Design

Policy discovery is nested:

- inner folds select transparent policy thresholds from training observations;
- outer folds evaluate untouched periods only;
- purging and embargo controls reduce overlapping-outcome leakage;
- every report includes raw signal count and effective independent sample size.

## Required Discipline

The frontier can show high precision only when it also passes coverage,
concentration, stability, and effective-sample constraints. A tiny sample with
excellent precision is reported as insufficient evidence rather than a success.

## CLI

```bash
poetry run python -m alpha replay precision-coverage-frontier
poetry run python -m alpha replay precision-coverage-frontier --direction buy
poetry run python -m alpha replay precision-coverage-frontier --direction sell
poetry run python -m alpha replay bidirectional-policy-audit --min-precision 0.70 --min-signals 100
poetry run python -m alpha replay directional-calibration
poetry run python -m alpha replay directional-policy-candidates
```

Supported output modes:

```bash
--format text
--format json --output report.json
--format csv --output report.csv
--group-by year|regime|setup|timing|horizon|policy
```
