# Strategy and Indicator Combination Backtest Lab

## Purpose

The Strategy Lab is Project Alpha's bounded, interpretable historical research
environment. It compares strategy and indicator combinations under one point-in-time
dataset, one versioned execution profile, and one metric contract.

It cannot change recommendation logic, `APPROVAL_POLICY_V1`, forward-validation
cohorts, allocation, live execution, or production strategy state.
`PRODUCTION_INFLUENCE=false` is enforced by models, registries, CLI output, research
records, and IRD diagnostics.

## Evidence Classes

All reports retain one of these source classes:

- `AUTHORITATIVE`
- `RECONSTRUCTED`
- `PROVISIONAL`
- `FORWARD_OBSERVED`

Strategy evidence labels separately report sample and validation maturity. A positive
result from reconstructed rows remains `RECONSTRUCTED_RESEARCH_ONLY` and cannot be
published as deployment-ready.

## Existing Infrastructure Reused

- `HistoricalSignalGenerator` supplies point-in-time `DiscoveryRow` records.
- `FeatureManifest` supplies the usable-feature allow-list and quarantine ledger.
- `CandidateStrategyGenerator` supplies the bounded, deterministic base search.
- `StrategyEvaluator` supplies established matching semantics.
- `MultipleTestingControl` supplies the existing family-wise adjustment.
- `ResearchExperimentRegistry` records the governed experiment.
- The IRD diagnostic registry discovers the lab through its plugin interface.

The lab does not implement a second historical replay framework.

## Components

- `IndicatorRegistry`: point-in-time metadata, provenance, lineage, defects, and
  quarantine state.
- `StrategyTemplateRegistry`: 17 interpretable strategy and benchmark templates.
- `CombinationGenerator`: combines existing bounded rules with versioned entry, stop,
  target, holding-period, and execution dimensions.
- `TradeSimulator`: conservative OHLC lifecycle simulation for entry, stops, targets,
  partial exits, trailing stops, gaps, and unresolved same-bar ordering.
- `PerformanceMetricsEngine`: gross/net trade, risk, portfolio, concentration, and
  evidence metrics.
- `TimeSeriesAnalysis`: annual, quarterly, rolling 20/50-trade, equity, and underwater
  series.
- `ComponentAttributionEngine`: matched with/without comparisons and lineage flags.
- `CombinationAttributionEngine`: opportunity, symbol, period, and winner concentration
  explanations.
- `LabRobustnessAnalyzer`: confidence intervals, cost/slippage stress, stability, and
  multiple-testing adjustment.
- `StrategyLeaderboard`: composite and single-metric research views.
- `StrategyLabExperimentRegistry`: immutable experiment and failed-strategy memory with
  JSON/CSV export.

## Historical Simulation Modes

### Bar-Level Lifecycle

When chronological OHLC bars and frozen levels are supplied, `TradeSimulator` supports:

- next-open and next-close entry;
- preferred, aggressive, confirmation, breakout, and zone entry;
- recorded, fixed-percent, ATR, support, swing-low, and volatility stops;
- recorded, fixed-R, partial, trailing, and time exits;
- gap-through-stop fills at the open;
- conservative stop-first ordering when one daily bar touches stop and target;
- explicit costs, slippage, MFE, MAE, R multiple, and missed-entry reason.

### Reconstructed Outcome Proxy

The current 1,500-row population has reconstructed returns and excursions but does not
provide authoritative bar-level fill ordering for every candidate. Default lab runs
therefore compare strategies using `RECONSTRUCTED_OUTCOME_PROXY`. They do not infer
unavailable fills, delayed-entry effects, stop gaps, or target ordering.

## Execution Profile

`strategy-lab-execution-v1` uses an explicit research assumption equivalent to the
existing discovery profile:

- 20 bps configured transaction cost per round trip;
- 10 bps configured slippage per round trip;
- 0.30% total round-trip cost;
- 10% research capital allocation per sequential trade;
- five-session entry-validity window;
- 50% partial exit fraction;
- stop-first ambiguous-bar ordering.

Individual statutory fields remain zero because the profile does not assert a current
legal or brokerage fee schedule.

## Ranking Discipline

Default ranking is not precision-only. Its transparent research score includes
expectancy, profit factor, drawdown, positive-period stability, sample size, cost
robustness, and concentration. Scores below 30 completed trades receive a continuous
sample-sufficiency multiplier. Tiny samples remain visible in specialized views but
cannot lead the default ranking solely because of high precision.

## Attribution Limits

Attribution is associative, not causal. A component is `LINEAGE_CONFOUNDED` when a
matched strategy contains overlapping same-source features. This includes component
scores embedded in the recommendation score. The lab never claims independent value
from an overlapping feature without an otherwise-identical valid ablation.

## Persistence

The default registry is `.alpha/strategy_lab/experiment_registry.json`. Every tested
strategy, including failures, stores its immutable rule hash, assumptions, evidence,
metrics, timeline, robustness, classification, and rejection reasons. Repeating an
identical experiment is idempotent. A changed payload under the same experiment ID is
rejected.

## Commands

```text
poetry run python -m alpha strategy-lab inventory
poetry run python -m alpha strategy-lab generate
poetry run python -m alpha strategy-lab backtest
poetry run python -m alpha strategy-lab leaderboard
poetry run python -m alpha strategy-lab compare
poetry run python -m alpha strategy-lab attribution
poetry run python -m alpha strategy-lab timeline
poetry run python -m alpha strategy-lab robustness
poetry run python -m alpha strategy-lab report
```

JSON or CSV export is selected from the extension passed to `--export`.

## Production Boundary

The lab nominates research only. No strategy is automatically promoted or published to
shadow validation. `PRODUCTION_INFLUENCE=false`.
