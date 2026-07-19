# TradingView Limitations

## Data Boundary

TradingView chart data is selected and adjusted by TradingView and its data
providers. It is not the Alpha Market Truth Engine. Corporate actions, symbol
changes, series history, delistings, exchange sessions, correction timing,
volume, and rounding can differ.

Permanent notice:

```text
DATA SOURCE: TRADINGVIEW
NOT ALPHA MARKET TRUTH ENGINE
CORPORATE-ACTION AND SYMBOL-HISTORY SEMANTICS MAY DIFFER
RESULTS ARE INDEPENDENT VALIDATION, NOT AUTHORITATIVE ALPHA REPLAY
```

## Unavailable Systems

An ordinary single-symbol Pine strategy cannot faithfully reproduce:

- full-market candidate ranking and simultaneous candidate comparison;
- point-in-time historical universes and survivorship-safe screening;
- historical sector membership and sector-wide ranking;
- proprietary breadth and market-state snapshots;
- Market DNA and Institutional Research Director state;
- outcome-ledger calibration, posterior probabilities, or adaptive confidence;
- institutional capacity, liquidity, portfolio fit, correlations, and exposure;
- live-feed health and staleness gates;
- corporate-action evidence lineage and warehouse confidence scoring.

These are marked unavailable or excluded. Manual inputs and benchmark proxies
are visible approximations, never hidden replacements.

## Execution Boundary

Alpha's outcome evaluator starts strictly after a frozen recommendation and
uses conservative stop-first ordering when a stop and target share a bar.
TradingView's Strategy Tester owns Pine fills. Commission, slippage,
process-on-close, next-bar signaling, partial exits, target touches, and session
settings can produce different paths even with identical OHLCV.

Pine's strategy declaration requires some controls to be compile-time values.
Scripts expose matching research inputs and label declaration-fixed controls;
changing those assumptions requires regenerating or editing the declaration and
recording the resulting source hash.

## Interpretation

The suite answers whether a transparent Pine-compatible technical hypothesis
survives an independent chart-data backtest. It does not establish that Alpha's
production policy would have selected, sized, or approved the same trade.

No output may be labelled `ALPHA_EXACT`.
