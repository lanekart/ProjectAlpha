# No-Repainting Audit

## Rules Enforced

- Pine v6 only.
- Future-value merge modes are prohibited by static validation.
- Every `request.security()` call explicitly disables future access.
- Multi-timeframe entry evidence requests the last completed higher-timeframe
  expression with `[1]`.
- Entries require confirmed chart bars.
- The multi-timeframe script blocks entry if confirmed-bars mode is disabled.
- No future market-regime value is requested.
- No unconfirmed pivot is used for a historical entry.
- Setups are assigned from evidence available on the decision bar and are not
  retroactively rewritten.
- Intrabar high/low touch assumptions are disclosed as execution assumptions,
  not confirmed close evidence.

## Bar Merge Semantics

Higher-timeframe requests use gaps-off merging and explicit future-access
prevention. The `[1]` expression deliberately adds up to one completed
higher-timeframe bar of latency. That latency is preferable to using an
incomplete higher-timeframe candle and is recorded as a semantic difference
from any Alpha input timestamped at a different market close.

Single-symbol benchmark requests may use the current completed chart bar. They
do not supply future bars. Benchmark proxies remain approximations and cannot
be called Alpha's market regime or relative-strength pipeline.

## Static Audit Coverage

`PineStaticValidator` checks:

- version header;
- one source declaration;
- prohibited future-data constructs;
- explicit safe merge settings for every security request;
- missing conservative strategy controls;
- missing permanent data warnings;
- leaked Python values in generated Pine;
- source-size awareness.

Static checks cannot prove TradingView compiler acceptance or provider bar
semantics. Manual compilation and the incomplete-higher-timeframe fixture are
mandatory.

## Finding

No intentional future leak or repainting entry path is present in the checked-in
suite. Status remains conditional on manual TradingView compilation:

```text
NO_LOOKAHEAD=true
NO_REPAINTING=true
TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED
TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED
```
