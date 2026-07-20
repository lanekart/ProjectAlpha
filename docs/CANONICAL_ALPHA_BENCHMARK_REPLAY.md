# Canonical Alpha Benchmark Replay (CABR v1.0)

## Purpose

CABR freezes the current Alpha research and decision stack and measures it over
the observed historical market population. Its canonical run is permanently
identified as `ALPHA_BASELINE_v1.0`.

CABR is a scientific benchmark, not an optimization engine. It does not tune a
threshold, promote a policy, place an order, or influence production.

`PRODUCTION_INFLUENCE=false`

## Honest Replay Classification

The baseline is an `OBSERVED_MARKET_REPLAY` because authoritative historical
NIFTY constituent membership is unavailable. It must never be described as an
index replay.

Historical sector membership is also unavailable. CABR preserves that status as
unknown and does not claim current sector labels were valid in the past.

## Frozen Stack

`manifest.json` records the version and SHA-256 content hash of:

- legacy warehouse;
- feature stack;
- candidate generation;
- setup discovery;
- feature attribution;
- institutional approval policy;
- trade-plan policy;
- decision engine;
- source commit and source tree;
- Python runtime;
- Poetry lock file;
- retrospective opportunity-label evidence.

The manifest also stores replay dates, portfolio assumptions, universe
classification, point-in-time assertions, artifact hashes, and explicit unknowns.
An existing baseline directory rejects a replay with a different input hash.

## Point-in-Time Contract

Each session uses only records dated on or before that session. The frozen
canonical runner retrieves at most 250 historical bars per selected candidate
with `trade_date <= observed_on`.

Future observations are permitted only after a decision, for outcome and
opportunity-capture measurement. They never enter candidate generation,
features, scoring, ranking, approval, or portfolio selection.

Retrospective major-opportunity and tradable-onset artifacts are separately
hashed and labelled as evaluation evidence.

## Canonical Portfolio Policy

Defaults reproduce the current research allocation and execution assumptions:

| Parameter | Default |
|---|---:|
| Initial capital | INR 10,00,000 |
| Maximum positions | 3 |
| Position size | 10% |
| Cash reserve | 70% |
| Maximum single name | 10% |
| Maximum sector exposure | 25% |
| Transaction cost | 0.20% round trip |
| Slippage | 0.10% round trip |
| Entry validity | 5 sessions |

Parameterized runs receive a content-derived `CABR_RESEARCH_*` identity and do
not replace `ALPHA_BASELINE_v1.0`.

## Execution Semantics

- Decisions are made after the session's observed data.
- Entry can occur only on a later session.
- Entry zones, confirmation levels, maximum chase prices, recorded stops,
  targets, ATR trails, and holding limits are preserved.
- A stop is evaluated before a target when both touch in the same bar.
- Gap-through stops fill conservatively at the opening price.
- Target 1 may realize a partial profit and move the stop to breakeven.
- Remaining exposure can exit at the runner target, trailing stop, time limit,
  or replay boundary.
- Missing execution evidence fails closed.

The current canonical approval policy produced no institutional approvals in
the frozen historical audit. CABR therefore executes no trade and holds cash;
it does not relax the gate to manufacture a portfolio track record.

## Metrics and Artifacts

CABR reports opportunity flow by session, week, month, and year; trade outcomes;
exit attribution; portfolio performance; deployment and idle capital; major
opportunity capture; rejection attribution; and available benchmarks.

Artifacts:

- `executive_report.md`
- `portfolio_statistics.csv`
- `trade_log.csv`
- `position_history.csv`
- `capital_curve.csv`
- `drawdown_curve.csv`
- `monthly_returns.csv`
- `yearly_returns.csv`
- `candidate_statistics.csv`
- `approval_statistics.csv`
- `opportunity_capture.csv`
- `idle_capital.csv`
- `benchmark_comparison.csv`
- `manifest.json`

Undefined statistics remain `unavailable`. For example, a zero-trade baseline
has no win rate, profit factor, expectancy, Sharpe, Sortino, or Calmar ratio.

## Benchmarks

NIFTY 50 buy-and-hold is included only when genuine historical index OHLC exists
in the frozen warehouse. Otherwise it is explicitly unavailable.

The observed equal-weight universe is a provisional comparison. It is the daily
equal-weight return of securities present in the observed population, without
costs. It is not an investable index and inherits legacy corporate-action and
identity limitations.

## Commands

```text
poetry run python -m alpha benchmark replay
poetry run python -m alpha benchmark report
poetry run python -m alpha benchmark trades
poetry run python -m alpha benchmark portfolio
poetry run python -m alpha benchmark opportunity
```

Replay options include `--start`, `--end`, `--capital`, `--max-positions`,
`--transaction-cost`, `--slippage`, `--json`, and `--csv`.

## Research Governance

Future Alpha changes are eligible for production consideration only after they
are evaluated against the same warehouse, replay period, execution assumptions,
and portfolio policy as `ALPHA_BASELINE_v1.0`. A better isolated metric is not
enough; comparisons must consider opportunity capture, expectancy, drawdown,
capital use, and reproducibility together.

## Diagnostic Signal Audit

The diagnostic signal audit evaluates raw `BUY` and `STRONG_BUY` verdicts that
were not part of an eligible decision population. The replay evidence preserves
the original final signal so the audit never reconstructs or guesses verdicts.

Fixed 1, 5, 10, and 20-session horizons report forward close return, maximum
favorable excursion, and maximum adverse excursion. A horizon is observed only
when every required symbol/session candle exists. Missing observations and the
right replay boundary are explicitly censored.

Artifacts are deterministic:

- `signal_outcomes.csv`;
- `summary.json`;
- `report.md`;
- `manifest.json` with input and artifact hashes.

Run after generating benchmark artifacts:

```text
poetry run python -m alpha benchmark signal-audit \\
  --benchmark-output .alpha/benchmark/<RUN_ID> \\
  --database alpha_data/warehouse/historical_truth.duckdb \\
  --historical-truth-snapshots alpha_data/snapshots \\
  --start 2026-01-01 \\
  --end 2026-07-20
```

This audit does not measure deployable strategy performance, tune thresholds,
or change approval or portfolio policy.

`DIAGNOSTIC_ONLY=true`

`PRODUCTION_INFLUENCE=false`
