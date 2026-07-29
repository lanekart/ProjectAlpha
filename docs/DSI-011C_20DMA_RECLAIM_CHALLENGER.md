# DSI-011C — 20-DMA Reclaim Portfolio Challenger

## Objective

Test one frozen, research-only challenger designed for a materially better
return-to-drawdown profile than the existing equal-weight stop-target matrix.
The empirical hurdle is aspirational: gross CAGR above 14% with maximum
drawdown below 12%. No result is assumed before execution.

## Frozen signal definition

A signal is eligible only when every condition is true on the signal-session
close:

1. The retrospective frozen Alpha verdict is `BUY` or `STRONG_BUY`.
2. The frozen Alpha market regime is `POSITIVE`.
3. Adjusted close is above the point-in-time 200-session simple moving average.
4. The 20-session simple moving average is above its value five sessions ago.
5. The prior close was at or below the prior 20-session simple moving average.
6. The current close is above the current 20-session simple moving average.
7. RSI(14) is at least 50.
8. Mean volume over the three sessions preceding the signal is no greater than
   mean volume over the 20 sessions preceding the signal.
9. Signal-session volume is at least 1.5 times the preceding 20-session mean.

This is a close-based reclaim, not a generic `close > 20-DMA` state.

## Entry and prioritisation

- Entry occurs at the next valid eligible-equity session open.
- When more candidates exist than portfolio capacity, ordering is:
  1. `STRONG_BUY` before `BUY`;
  2. higher frozen recommendation score;
  3. governed security identifier.
- Whole shares only.
- Maximum five concurrent positions.

## Position risk

- Initial stop is exactly 5% below entry.
- Normal new-position risk is 1% of opening portfolio equity.
- New-position risk falls to 0.5% when previous-close portfolio drawdown is at
  least 8%.
- Quantity is bounded by both the risk budget and available cash.

## Exits

- Conservative stop-first handling is mandatory when daily OHLC cannot resolve
  whether a stop or target occurred first.
- Exit 50% at 2R when quantity permits.
- Exit the balance at the earliest of:
  - 3R;
  - the prior-session 20-DMA trailing stop after the 2R event;
  - 40 completed holding sessions.
- Adverse stop gaps fill at the session open.
- Target gaps fill at the better of the target or session open, matching the
  existing governed research fill convention.

## Portfolio hard stop

When close-to-close portfolio drawdown reaches or exceeds 12%:

1. all open positions are liquidated at that session close;
2. pending entries are cancelled;
3. no further entries are permitted for the remainder of the research window.

This is deliberately severe. It tests whether the challenger can meet the
stated drawdown boundary without resetting its high-water mark or hiding losses
through a synthetic restart.

## Data and governance

- Data window begins no earlier than 2016-01-01.
- Price source is the certified `research_daily_candle` table.
- Signal source is `RETROSPECTIVE_FROZEN_ALPHA_REPLAY`.
- Retrospective recommendations are not represented as historically issued
  recommendations.
- Transaction costs: `NONE`.
- Slippage: `NONE`.
- Results are gross of costs.
- Automatic strategy promotion is disabled.
- `PRODUCTION_INFLUENCE=false`.

## Command

```bash
poetry run python -m alpha.research.reclaim_portfolio_challenger \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --output .alpha/research/dsi011c_20dma_reclaim
```

The run writes JSON, CSV, Markdown, trade, equity, signal-audit, and manifest
artifacts with a deterministic logical SHA-256.
