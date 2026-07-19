# TradingView Research Laboratory v2.0

## Purpose

The TradingView Research Laboratory (TRL) is a hypothesis accelerator for
Project Alpha. Its only decision question is:

> Does this measured change improve the current Alpha baseline?

TRL is not a stock recommendation surface, an execution system, or an
authoritative replay engine. TradingView data remains secondary evidence.

`PRODUCTION_INFLUENCE=false`

## Architecture

```text
Alpha canonical baseline
  -> TradingView indicator, strategy, risk, and timeframe labs
  -> immutable measured experiment intake
  -> exact-cohort comparative engine
  -> candidate ranking
  -> Alpha replay and walk-forward validation only
```

The canonical baseline is extracted from Alpha's current evidence weights by
`alpha/tradingview_research/baseline.py`. The baseline manifest records its
stable configuration identifier. New indicators such as RSI, MACD, ADX, and
VWAP are available as research toggles but are disabled in the Alpha baseline.

## Pine Laboratories

| Script | Research responsibility |
|---|---|
| `Alpha_TRL_01_Indicator_Weight_Ablation_Lab.pine` | Independent indicator toggles, component weights, and baseline/removal ablations |
| `Alpha_TRL_02_Strategy_Combination_Lab.pine` | Nine setup families with ANY, ALL, minimum-N, and weighted combination rules |
| `Alpha_TRL_03_Stop_Exit_Lab.pine` | Six stop families and nine exit families with stop-out, R, drawdown, and holding-period output |
| `Alpha_TRL_04_Multi_Timeframe_Lab.pine` | Monthly, weekly, daily, 4-hour, and 1-hour trend/setup/entry combinations using confirmed bars |

Each script is standalone, Pine v6, long-only, and carries the permanent data
provenance warning. Each uses three compact panels:

1. research state, setup, and entry state;
2. measured strategy metrics;
3. comparison with the manually supplied matching Alpha baseline.

No script labels a chart result as an Alpha recommendation.

Reference renderings, using explicitly non-empirical demo values, are stored at:

- `docs/pine/assets/trl_dashboard_reference.png`
- `docs/pine/assets/trl_comparison_reference.png`

## Alpha Modules

- `models.py`: immutable configurations, observations, comparisons, and
  promotion decisions.
- `baseline.py`: current canonical configuration and intake template.
- `comparison.py`: exact partition, symbol, sector, and date-window matching.
- `promotion.py`: fail-closed development, validation, holdout, drawdown,
  expectancy, symbol-diversity, and sector-diversity gates.
- `grid.py`: bounded development-only weight grids.
- `variants.py`: predeclared component-ablation, stop/exit, and multi-timeframe
  configuration families generated before results are observed.
- `batch.py`: deterministic one-symbol-per-chart run plans.
- `aggregation.py`: sector summaries and symbol-level metric distributions with
  explicit missing-observation counts.
- `registry.py`: append-safe JSON evidence registry plus JSON/CSV export.
- `ranking.py`: evidence-only ranking with no synthetic opportunity score.
- `rendering.py`: concise research and promotion reports.

## CLI

```text
poetry run python -m alpha trl baseline
poetry run python -m alpha trl template --output experiment.json
poetry run python -m alpha trl register --input experiment.json
poetry run python -m alpha trl report --experiment-id ID
poetry run python -m alpha trl promote --experiment-id ID
poetry run python -m alpha trl rank
poetry run python -m alpha trl sector-report --experiment-id ID
poetry run python -m alpha trl symbol-report --experiment-id ID --partition HOLDOUT
poetry run python -m alpha trl registry --json-output registry.json --csv-output registry.csv
poetry run python -m alpha trl weight-grid --input grid.json --output variants.json
poetry run python -m alpha trl variant-plan --family COMPONENT_ABLATION --output ablations.json
poetry run python -m alpha trl batch-plan --input universe.json --output runs.json
poetry run python -m alpha trl scripts
```

The default registry is `.alpha/tradingview_research/experiments.json` and can
be overridden with `ALPHA_TRL_REGISTRY` or `--registry`.

## Sector And Symbol Laboratories

Pine does not provide Alpha's point-in-time NIFTY membership or historical
sector identity. A universe manifest must therefore be produced from an
authoritative point-in-time source. `batch-plan` materializes one auditable run
per symbol and partition. Alpha then aggregates sector and universe
distributions from registered observations.

This design avoids relying on one chart and stays within TradingView's
request-call and execution budgets. It supports NIFTY 50, NIFTY 100, NIFTY 200,
and custom watchlists when authoritative membership is supplied; it does not
invent membership.

## Candidate Promotion

A treatment is eligible only for `PROMOTE_TO_ALPHA_REPLAY` when all of the
following are measured:

- development, validation, and holdout periods are present and chronological;
- each treatment observation has an exact matching baseline population;
- every matched cohort has completed trades and available expectancy/drawdown;
- expectancy improves in every matched cohort;
- maximum drawdown improves or stays unchanged in every matched cohort;
- validation and holdout cover at least two symbols and two sectors.

Failure of any condition returns `REJECT`. Passing TRL never changes Alpha and
never approves capital. The next stage is Alpha replay, walk-forward testing,
and future Market Truth Engine warehouse validation.

## Compilation Status

- `PINE_STATIC_VALIDATION=PASS`
- files in TRL: 4
- full Pine inventory: 27
- static errors: 0
- static warnings: 0
- `TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED`

Manual TradingView compilation and runtime verification require an
authenticated TradingView session. Static validation is not represented as a
provider compile.

## Official Platform References

- [Pine Script v6 reference](https://www.tradingview.com/pine-script-reference/v6/)
- [Pine v6 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/)
- [Pine limits](https://www.tradingview.com/pine-script-docs/writing/limitations/)
- [Profiling and optimization](https://www.tradingview.com/pine-script-docs/writing/profiling-and-optimization/)
