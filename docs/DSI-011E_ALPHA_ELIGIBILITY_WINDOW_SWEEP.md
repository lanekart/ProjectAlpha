# DSI-011E — Alpha Eligibility-Window Sweep

## Purpose

DSI-011E tests whether the low utilisation of the governed DSI-011C 20-DMA
reclaim portfolio is caused by requiring the Alpha recommendation and the
technical entry trigger to occur on the same session.

This milestone is diagnostic and research-only. It cannot change production
recommendations, approval policy, portfolio construction, or risk policy.

## Frozen population

An Alpha `BUY` or `STRONG_BUY` establishes temporary eligibility. Regime is
retained for attribution only and is not a hard gate. The entry trigger remains
unchanged:

- close above point-in-time SMA(200);
- rising SMA(20), measured against five sessions earlier;
- close-based SMA(20) reclaim;
- RSI(14) at least 50;
- prior three-session average volume no greater than the prior 20-session
  average;
- trigger-session volume at least 1.5 times the prior 20-session average.

Entry remains the next valid eligible-equity session open.

## Window contract

The exact pre-registered windows are:

- 1 session, including the Alpha signal session;
- 3 sessions;
- 5 sessions;
- 10 sessions;
- 20 sessions.

A newer Alpha signal for the same security supersedes an older unconsumed
eligibility record. An eligibility record is consumed by its first qualifying
technical trigger. Untriggered records expire after the specified number of
eligible security sessions. No future Alpha signal can influence an earlier
technical trigger.

## Risk-policy contract

Each window is tested under both policies:

1. flat 1.0% initial portfolio risk per new position, throttled to 0.5% after
   an 8% drawdown;
2. uniform 1.5% initial portfolio risk per new position, throttled to 0.75%
   after an 8% drawdown.

Both policies retain:

- maximum five positions;
- fixed 5% initial stop;
- 50% exit at 2R;
- remaining exit at 3R, prior-session SMA(20) trail, or 40 sessions;
- conservative stop-first daily ambiguity handling;
- full liquidation and permanent termination of new entries at a 12%
  close-based portfolio drawdown.

The complete matrix contains exactly 10 cells.

## Parity boundary

The one-session flat-1% cell must reproduce the certified DSI-011C neutral
reference within `0.0001` percentage points for total return, CAGR, and maximum
drawdown, and exactly for signals, entries, and completed trades. The sweep
fails closed if parity does not hold.

## Evidence and interpretation

The sweep exports aggregate JSON, CSV, Markdown, a logical hash manifest, and
per-cell trigger, trade, rejection, and equity evidence.

Results remain:

- retrospective frozen Alpha replay evidence;
- gross of transaction costs and slippage;
- unvalidated on a fresh untouched external holdout;
- descriptive only, with no automatic strategy promotion.

`PRODUCTION_INFLUENCE=false`.
