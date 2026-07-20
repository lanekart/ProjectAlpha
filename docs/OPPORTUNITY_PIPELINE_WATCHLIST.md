# Opportunity Pipeline and Watchlist Governance

## Purpose

The opportunity pipeline preserves high-quality bullish candidates that fail only on
execution readiness or current reward/risk. It prevents those candidates from being
collapsed into generic rejections while leaving every institutional deployment gate
unchanged.

`WATCHLIST` is a non-executable research and monitoring state. It never authorizes
capital deployment.

## Actions

- `BUY`: all institutional, stress, and trade-plan requirements pass.
- `WATCHLIST`: directional and setup quality remain strong, but entry timing,
  stop distance, confirmation, or reward/risk is not currently deployable.
- `REJECT`: a hard direction, evidence, data, liquidity, historical-edge,
  contradiction, or risk-control requirement fails.

## Watchlist admission

A candidate can enter the watchlist only when:

1. The directional verdict is `BUY` or `STRONG_BUY`.
2. The final evidence score is at least 85.
3. The setup scorecard is at least 70.
4. Data and capacity are sufficient.
5. No bearish-indicator contradiction is present.
6. Historical expectancy is not negative.
7. Gate failures are limited to execution-readiness reasons:
   - poor reward/risk;
   - stop distance too wide;
   - pending trigger;
   - late entry.
8. No hard stress-test veto is present.

## Watchlist reasons

- `UNFAVOURABLE_RISK_REWARD`
- `STOP_DISTANCE_TOO_WIDE`
- `ENTRY_EXTENDED`
- `WAIT_FOR_PULLBACK`
- `WAIT_FOR_CONSOLIDATION`
- `WAIT_FOR_CONFIRMATION`

## Promotion triggers

Every watchlist item must state at least one measurable condition that could promote
it to `BUY`, such as:

- reward/risk improves to at least 2R;
- a structure-based stop becomes 10% or tighter;
- a constructive pullback completes without breaking the bullish trend;
- a tight consolidation restores favourable execution asymmetry;
- the required entry trigger becomes confirmed.

## Tatva Chintan case

The 16 July 2026 Tatva Chintan case motivates this classification. A bullish trend
and setup can remain attractive while fresh deployment is blocked by an extended
entry or wide stop. The correct governed output is therefore not an executable buy
and not a forgotten rejection. It is a watchlist item with an explicit explanation
and promotion conditions.

This case is illustrative only. It does not relax thresholds or prove that every
extended bullish setup should be watchlisted.

## Non-goals

This milestone does not introduce trend-lifecycle scoring, volume-efficiency scoring,
dynamic allocation, new indicators, or relaxed institutional approval policy. Those
ideas require broader evidence before implementation.
