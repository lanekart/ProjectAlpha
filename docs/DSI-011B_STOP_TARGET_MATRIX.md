# DSI-011B — Governed Stop × Target Matrix

## Objective

Execute the exact stop and target policy cross-product pre-registered by the
DSI-011A acceptance conversation against one frozen entry population.

The matrix is finite and explicit:

- Stops: 5%, 8%, 10%, 2 ATR, and `STOP-STRUCTURAL-10D`.
- Targets: 10%, 20%, 2R, 3R, and no fixed target.
- Total combinations: 25.

## Frozen entry population

Every matrix cell uses the same retrospective frozen Alpha entry definition:

- Alpha `BUY` and `STRONG_BUY` signals;
- RSI(14) above 50;
- close above the 200-session SMA;
- volume at least 1.5 times its 20-session average;
- next-valid-session open entry;
- ten maximum concurrent positions;
- twenty-session maximum holding period;
- stop-first handling when a daily candle touches stop and target;
- equal-weight, whole-share accounting.

No entry condition, portfolio setting, date boundary, ambiguity policy or signal
source changes between matrix cells.

## Execution-level validity

A combination fails closed and is excluded from ranking when any completed trade
has a requested level that is:

- absent;
- non-positive;
- a stop at or above entry; or
- a target at or below entry.

Invalid cells remain in the exported matrix with counts and samples. They are not
silently repaired, deleted or promoted.

## Command

```bash
poetry run python -m alpha.research.stop_target_matrix \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --output .alpha/research/dsi011b_stop_target_matrix
```

## Outputs

- `stop_target_matrix.csv`
- `stop_target_matrix.json`
- `stop_target_matrix.md`
- `matrix_manifest.json`
- per-cell specifications, summaries and execution-level audits under `runs/`

## Governance

- Results remain gross of brokerage, statutory costs, spread, slippage and market
  impact.
- No strategy or stop policy is automatically promoted.
- Retrospective Alpha signals are not represented as historically issued signals.
- `PRODUCTION_INFLUENCE=false`.
