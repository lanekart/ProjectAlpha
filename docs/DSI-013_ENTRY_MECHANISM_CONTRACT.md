# DSI-013 Entry Mechanism Contract

## Purpose

This contract freezes the candidate-level execution rules evaluated after the
DSI-013 intraday source certificate is ready. It does not select a strategy,
simulate a portfolio, or permit live trading.

All mechanisms consume one certified identity/session bar sequence in one
consistent price basis. Every challenger triggers on a completed five-minute
bar and fills only at the following five-minute bar open. A qualifying trigger
without a next bar is `NEXT_BAR_UNAVAILABLE`; a fill beyond the frozen cutoff is
`ENTRY_CUTOFF_EXCEEDED`.

## Control

`ENTRY-NEXT-SESSION-OPEN`

- preserves the signed DSI-009 raw and after-slippage entry prices;
- records the first certified five-minute timestamp as execution-time lineage;
- does not re-estimate the control fill from intraday bars.

## ORB15 breakout

`ENTRY-ORB15-BREAKOUT`

- opening range: bars beginning at 09:15, 09:20, and 09:25;
- evaluation begins with the 09:30 bar;
- trigger: completed close strictly above the opening-range high;
- fill: next five-minute open;
- latest permitted fill: 14:30.

## VWAP reclaim

`ENTRY-VWAP-RECLAIM`

- session VWAP uses cumulative typical-price multiplied by volume divided by
  cumulative volume;
- require at least one completed close below VWAP;
- trigger: a later completed close above VWAP whose bar volume exceeds the
  median volume of all prior completed session bars;
- fill: next five-minute open;
- latest permitted fill: 14:30.

## First pullback

`ENTRY-FIRST-PULLBACK`

- require an initial completed close above the opening-range high;
- impulse volume is the aggregate from the 09:30 evaluation boundary through
  the initial breakout bar;
- require at least two subsequent completed pullback bars;
- no pullback close may fall below contemporaneous session VWAP;
- aggregate pullback volume must remain below impulse volume;
- trigger: the first later completed bar closing above the immediately prior
  bar's high;
- only this first pullback is eligible;
- fill: next five-minute open;
- latest permitted fill: 14:30.

## Closing continuation

`ENTRY-CLOSING-CONTINUATION`

- evaluation bars begin from 14:30 through 15:10 inclusive;
- require close above session VWAP and opening-range high;
- require close within 0.5% of the session high observed through the trigger;
- require cumulative session volume at least 1.25 times the governed comparable
  session median total volume;
- missing comparable-volume evidence is `DATA_UNAVAILABLE`;
- fill: next five-minute open;
- latest permitted fill: 15:15.

## Slippage and terminal states

Challenger fill price applies the frozen base slippage in the DSI-013 policy.
The mechanism layer reports entry evidence only. Brokerage, statutory charges,
capacity, exits, expectancy, portfolio contention, multiple-testing controls,
and acceptance are evaluated in later governed layers.

Terminal states are:

- `ENTERED`;
- `NOT_ENTERED`;
- `DATA_UNAVAILABLE`;
- `NEXT_BAR_UNAVAILABLE`;
- `ENTRY_CUTOFF_EXCEEDED`.

No same-bar fill, repeated trigger attempt, averaging down, or same-day re-entry
is permitted.

## Validation boundary

The mechanism layer must pass locked Ruff, Ruff format, strict MyPy, synthetic
rule-specific tests, and every repository pytest shard. Passing this boundary
certifies deterministic mechanics only. It does not establish positive
expectancy or permit portfolio integration before the genuine source package is
ready.

## Governance

- `VALIDATED_STRATEGY=false`;
- `INTRADAY_LIVE_TRADING_ENABLED=false`;
- `AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false`;
- `EXECUTION_INFLUENCE=false`;
- `PRODUCTION_INFLUENCE=false`.
