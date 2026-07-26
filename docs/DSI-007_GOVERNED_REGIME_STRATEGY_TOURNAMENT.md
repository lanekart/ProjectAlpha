# DSI-007 Governed Regime-Aware Strategy Tournament

## Purpose

DSI-007 evaluates bounded, interpretable strategy rules over governed historical
market primitives. It does not reconstruct historical Alpha recommendation
objects and does not claim that its simulated signals were recommendations Alpha
issued at the time.

The subsystem is research-only:

```text
PRODUCTION_INFLUENCE=false
STRATEGY_AUTOMATIC_PROMOTION_ENABLED=false
DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false
```

## Research Boundary

The tournament:

1. admits an observation only when its ISIN resolves to one effective-dated
   governed identity;
2. requires a certified `BACKWARD_ADJUSTED` price-basis interval;
3. preserves securities that later renamed, merged, failed, or disappeared when
   they remain present in the governed historical evidence;
4. forms a signal at a session close and permits entry no earlier than the next
   governed session;
5. charges entry and exit costs and adverse slippage;
6. shares finite cash across overlapping positions;
7. selects strategies using training and validation periods that end before each
   outer test period;
8. treats cash or `NO_TRADE` as a valid selection;
9. treats parameter variants as related hypotheses;
10. refuses index-relative claims without a complete total-return benchmark.

The current adjusted-price population is a governed but partial cohort. It is not
a full-market index and its equal-weight baseline is explicitly labelled
non-investable. This limits external validity even when the simulated portfolio
curve itself is mechanically valid.

## A-J Sequence

### A. Data and Benchmark

The engine audits adjusted OHLCV, effective-dated identity joins, impossible
prices, duplicates, corporate-action conflicts, price-basis intervals, source
hashes, and benchmark coverage. A price index is never substituted for a missing
total-return index.

### B. Point-in-Time Regime

Regimes use only contemporaneous or trailing market level, breadth, and
volatility. The state observed at one close applies to the next session. Initial
warm-up sessions remain `UNKNOWN`.

### C. Strategy Grammar

The registry contains a fixed maximum of 24 variants and currently defines 13
variants across momentum breakout, trend following, pullback, relative strength,
volatility contraction, retest, mean reversion, avoidance, and no-trade
families. Stable IDs and deterministic duplicate fingerprints prevent accidental
search-space growth.

### D. Signals and Plans

Every signal records its data cutoff, identity, regime, strategy, source hash,
and next-session eligibility. Every plan freezes entry, ATR/structure risk,
2R/3R/4R targets, a two-ATR trail, and a maximum holding period.

### E. Portfolio Simulation

The simulator applies:

- finite starting capital;
- maximum open positions;
- maximum position and gross exposure;
- one percent average traded-value capacity;
- next-session open entry;
- adverse slippage;
- transaction costs on both sides;
- stop-first same-bar ordering;
- frozen target, trailing-stop, time-exit, and end-of-data rules.

### F. Walk-Forward Selection

Annual outer folds begin only after a four-year initial training history and one
validation year. The outer test period never contributes to its own strategy
selection. The objective combines validation return, volatility, downside, sample
size, and complexity. Non-qualifying mappings select `NO_TRADE`.

### G. Comparison Portfolios

DSI-007 compares:

- regime-aware selected strategy;
- best fixed strategy;
- non-regime ensemble;
- simple momentum;
- simple trend;
- equal-weight eligible cohort;
- governed total-return benchmark when supplied.

### H. Performance

The package reports actual out-of-sample capital curves, gross and net CAGR,
drawdown, volatility, Sharpe, Sortino, Calmar, costs, turnover, exposure,
calendar-year returns, and rolling 12/36/60-month statistics. Benchmark-relative
metrics remain `UNKNOWN` when total-return evidence is unavailable or incomplete.

### I. Overfitting

The audit estimates one-sided return evidence with a deterministic monthly block
bootstrap so overlapping signals from the same market episode are not treated as
independent observations. It then applies Benjamini-Hochberg and Holm corrections
where at least 24 monthly blocks exist, reports insufficient-test states
otherwise, checks parameter-neighbour direction, and exposes security, year, and
regime concentration. It reruns the selected portfolio with higher costs, higher
slippage, a one-session entry delay, reduced position capacity, lower liquidity
capacity, a deterministic one-state regime-label perturbation, the best security
removed, the best month removed, and the best year removed. The broad governed
adjusted cohort and simpler strategies are compared explicitly. RAW,
alternate-benchmark, and historical large-cap comparisons remain unavailable
where their source contracts are not governed; they do not receive fabricated
results.

### J. Certification

The certificate binds:

- source hashes;
- A-J readiness;
- historical coverage;
- benchmark status;
- regime and strategy summaries;
- portfolio metrics;
- overfitting state;
- every support-artifact hash;
- executive-report hash;
- all governance flags.

No self-referential certificate hash is used. The public verifier detects
certificate edits, artifact edits, unsafe support paths, optional database drift,
and governance changes.

## CLI

Run:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-regime-strategy-tournament \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --start 2016-01-01 \
  --end 2025-12-24 \
  --benchmark AUTO \
  --output artifacts/dsi007_regime_strategy_tournament
```

Supply a CSV containing `date` and `total_return_index` (or `tri`/`value`) to
enable benchmark-relative analysis. `AUTO` deliberately resolves to unavailable
unless a governed series has been explicitly supplied.

Verify:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-regime-strategy-tournament-verify \
  --certificate artifacts/dsi007_regime_strategy_tournament/dsi007_strategy_tournament_certificate.json \
  --require-ready \
  --database alpha_data/warehouse/historical_truth.duckdb
```

## Artifact Contract

DSI-007 emits the permanent 31-file package required by the milestone: one
certificate, 29 schema-stable CSV ledgers, and one executive report. Empty ledgers
retain headers. Portable artifacts contain source basenames and hashes, never
machine-local absolute paths.

## Known Limitations

- No governed broad-market TRI is currently present in the frozen warehouse.
- The governed adjusted cohort is partial and is not a broad-market benchmark.
- Historical sector classifications are unavailable. The configured research
  sector cap is disclosed in the certificate but explicitly marked
  `UNAVAILABLE_NOT_ENFORCED`; no sector-relative claim or sector-capacity
  inference is made.
- The zero risk-free rate is a frozen research assumption, not an observed rate.
- RAW-price and alternate-benchmark robustness remain unavailable until their
  source contracts are governed; no result is invented.
- A DSI-007 winner can qualify only for forward paper research and still requires
  human approval and DSI-006 forward evidence.

## Production Isolation

DSI-007 adds one explicit benchmark command. It does not import into the
recommendation, approval, allocation, live, learning, or execution paths. It
does not write the historical-truth database or snapshots. It cannot promote a
strategy.

`PRODUCTION_INFLUENCE=false`
