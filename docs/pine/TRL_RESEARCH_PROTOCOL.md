# TRL Research Protocol

## 1. Freeze The Question

Define one hypothesis and one treatment configuration. Record the experiment
identifier before inspecting results. Do not combine unrelated indicator,
strategy, stop, exit, and timeframe changes in one experiment unless the
research question is explicitly about that combination.

## 2. Freeze Partitions

Create chronological, non-overlapping periods:

- `DEVELOPMENT`: choose and refine the hypothesis;
- `VALIDATION`: test the frozen treatment;
- `HOLDOUT`: final untouched evaluation.

Weight-grid generation is rejected outside `DEVELOPMENT`. Never tune a setting
after observing validation or holdout performance and then continue using the
same period as independent evidence.

## 3. Freeze Population

For every run record the symbol, sector, partition, start date, and end date.
Use the same values for the Alpha baseline and TradingView treatment. Point-in-
time universe and sector membership must come from authoritative Alpha data;
current membership must not be projected backwards.

## 4. Run TradingView

Use the chart symbol and timeframe declared by the run plan. Preserve:

- long-only mode;
- next-bar execution setting;
- commission and slippage assumptions;
- stop-first same-bar conflict policy;
- date window and trading session;
- confirmed higher-timeframe bars.

Record trade count, win rate, profit factor, expectancy, maximum drawdown, net
return, average winner, average loser, and risk-specific metrics where
available. Do not enter unavailable values as zero.

## 5. Register Immutable Evidence

Start from `tradingview/manifests/trl_experiment_template.json`. Add one
`ALPHA_BASELINE` and one `TREATMENT` observation for each exact population.

```text
poetry run python -m alpha trl register --input experiment.json
```

The registry is append-safe. Re-registering the identical experiment is
idempotent. Reusing an identifier with different evidence is rejected.

## 6. Compare And Promote

```text
poetry run python -m alpha trl report --experiment-id ID
poetry run python -m alpha trl promote --experiment-id ID
poetry run python -m alpha trl rank
```

Comparisons are computed only for exact population matches. Missing metrics,
zero completed trades, unmatched cohorts, chronological leakage, worse
drawdown, or non-improving expectancy fail closed.

`PROMOTE_TO_ALPHA_REPLAY` means only that the hypothesis may enter Alpha's own
replay and walk-forward process. It does not modify production policy.

## 7. Scientific Discipline

- Keep rejected experiments; negative results are evidence.
- Report all tested variants, not only the best chart.
- Prefer distributions across symbols and sectors over single-symbol results.
- Treat provider differences, symbol history, and corporate actions as material.
- Re-run the frozen treatment in Alpha's authoritative warehouse before any
  policy proposal.
- Require human approval through the normal governance process after replay and
  walk-forward validation.

`PRODUCTION_INFLUENCE=false`

