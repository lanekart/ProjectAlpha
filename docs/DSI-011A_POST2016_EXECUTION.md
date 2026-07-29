# DSI-011A Post-2016 Research Execution

## Purpose

DSI-011A turns the DSI-011 conversational boundary into a genuine,
point-in-time research product. It adds a complete certified daily research
price table and a clearly labelled retrospective frozen Alpha signal source.

The implementation is research-only:

`PRODUCTION_INFLUENCE=false`

## Certified Data

The permanent `research_daily_candle` table contains one governed row for each
official NSE source row in the certified period. Ordinary equity eligibility
requires:

- an observed NSE equity ISIN beginning with `INE`;
- an officially observed equity series in `EQ`, `BE`, `BZ`, `SM`, or `ST`;
- positive valid adjusted OHLC;
- a unique identity, series, and session key.

Rows outside that contract remain in the table as
`INELIGIBLE_NON_EQUITY`; they are not silently deleted. A security moving
between eligible equity series retains its exact governed ISIN identity.
Unproved predecessor/successor relationships remain separate identities.

For a row with no applicable prior multiplicative corporate action, adjusted
OHLC equals raw OHLC and both cumulative factors equal one. Rows before a
certified split, bonus, rights issue, or face-value action use the immutable
`adjusted_daily_candle` lineage. Raw candles are never updated.

Build and certify:

```bash
poetry run python -m alpha historical-truth research-price-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --start 2016-01-01 \
  --end YYYY-MM-DD
```

The contract fails closed on unresolved required factors, missing eligible
rows, duplicate identity sessions, invalid adjusted OHLC, or session
reconciliation failure.

## Signal Sources

The lab keeps three Alpha signal concepts separate:

- `RECORDED_HISTORICAL_ALPHA_SIGNAL`: a recommendation actually stored at the
  historical time;
- `RETROSPECTIVE_FROZEN_ALPHA_REPLAY`: a pinned Alpha engine evaluated later
  using only point-in-time inputs;
- `WALK_FORWARD_ALPHA_REPLAY`: a separately governed replay whose fitted
  components use only earlier observations.

A source is ready only when its certified run covers the experiment's entire
date range. A short smoke replay cannot unlock a full-period experiment.

Build the retrospective ledger:

```bash
poetry run python -m alpha research replay-frozen-alpha \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --start 2016-01-01 \
  --end YYYY-MM-DD \
  --source-commit COMMIT_SHA
```

The permanent `frozen_recommendation` ledger records exact identity, ISIN,
symbol, series, verdict, score, setup, strategy, regime, component evidence,
trade-plan evidence, source-data hash, feature version, engine version, and
signal-source state. It never describes retrospective output as recorded
history.

## Point-in-Time Protections

- Historical rows are keyed by governed identity, not ticker alone.
- Symbol reuse cannot pull another identity's indicator history.
- Indicator warm-up uses only prior and current sessions.
- Close-derived signals execute no earlier than the next valid session.
- Pure technical experiments do not depend on an Alpha recommendation table.
- Alpha and hybrid experiments require their explicitly selected signal source.
- "To date" resolves to the latest fully certified session.
- Requests before 2016 fail closed.

## Execution

```bash
poetry run python -m alpha research data-contract
poetry run python -m alpha research chat
poetry run python -m alpha research ask \
  "From 2016 to the latest certified session, buy when RSI(14) crosses \
  above 30, price is above the 200-DMA, and volume is at least 1.5 times \
  its 20-session average. Enter next open, use an 8% stop, a 20% target, \
  and exit after 40 sessions."
```

Run the governed A-I acceptance sequence:

```bash
poetry run python -m alpha research acceptance \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root .alpha/research/dsi011a_acceptance
```

Generated sessions and run folders live under `.alpha/research/` and are not
repository source. CI should publish the complete acceptance tree as a workflow
artifact. Compact certification summaries may be retained separately.

## Performance Boundary

Completed summaries include gross total return, gross CAGR, maximum drawdown,
drawdown duration, trade count, win rate, average winner and loser, payoff
ratio, expectancy, profit factor, exposure, turnover, holding period, and
same-session ambiguity counts.

All results use:

- `TRANSACTION_COST_MODEL=NONE`
- `SLIPPAGE_MODEL=NONE`
- `RESULTS_ARE_GROSS_OF_COSTS=true`

Results exclude brokerage, STT, exchange charges, GST, stamp duty, bid-ask
spread, slippage, and market impact. No experiment is automatically promoted.

