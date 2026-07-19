# TradingView Backtest Protocol

## Required Setup

1. Select the exact exchange-qualified ticker, not a similarly named listing.
2. Record the exchange, ticker, chart currency, session, and adjustment setting.
3. Select the prescribed chart timeframe and matching Alpha script.
4. Set the date interval, commission, slippage, order size, and session.
5. Keep long-only, zero pyramiding, and confirmed-bar controls at conservative
   defaults unless the experiment explicitly changes them.
6. Record stop, target, next-bar, and same-bar conflict assumptions.
7. Export Strategy Tester results and all script inputs.
8. Run development, validation, and holdout intervals separately.
9. Never optimize on the holdout interval.
10. Compare with Alpha only after chart-data, corporate-action, symbol-history,
    session, and execution differences are documented.

## Test Matrix

Run every serious candidate across bullish, bearish, and sideways intervals;
multiple sectors; liquid large caps; mid caps; and small caps only where the
chosen order size remains realistic. Aggregate net profit alone is not a
promotion criterion.

For each strategy use at least:

- Development: hypothesis formation and parameter selection.
- Validation: one frozen parameter set.
- Holdout: untouched until the candidate and protocol are frozen.

## Data Record

Each exported result must record:

- ticker and exchange;
- chart timeframe and all requested higher timeframes;
- observable adjustment and session settings;
- start/end dates;
- script version and Alpha framework version;
- source commit and manifest hash;
- initial capital, sizing, costs, slippage, and pyramiding;
- fill and same-bar conflict assumptions;
- enabled setup, component, stop, target, and exit models.

## Fixture Verification

Use `tradingview/fixtures/parity_cases.json`. Load equivalent synthetic bars in
a private TradingView test symbol or replay fixture, record the visible script
result, and compare it with `pine_expected` using the stated tolerance. A case
marked unavailable is a disclosure test, not a numeric equality test.

## Acceptance Status

Local checks can report:

```text
PYTHON_GENERATION_TESTS=PASS
PINE_STATIC_VALIDATION=PASS
```

Until every source is compiled and fixture-tested in TradingView, report:

```text
TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED
TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED
```
