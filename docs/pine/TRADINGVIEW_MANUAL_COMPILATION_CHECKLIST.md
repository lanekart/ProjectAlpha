# TradingView Manual Compilation Checklist

## Prepare

1. Run `poetry run python -m alpha pine regenerate`.
2. Run `poetry run python -m alpha pine validate --all --strict`.
3. Confirm all six files in `tradingview/generated/` start with
   `//@version=6` at byte zero.

## Compile Every Variant

For each generated `.pine` file:

1. open TradingView Pine Editor;
2. replace the editor contents with the complete generated file;
3. save it as a new private script;
4. select **Add to chart**;
5. record compiler errors and warnings verbatim;
6. record `PASS` only when TradingView reports no compiler error.

Files:

- `Alpha_01_Component_Audit.pine`
- `Alpha_02_Setup_Comparator.pine`
- `Alpha_03_Institutional_Composite.pine`
- `Alpha_04_Multi_Timeframe_Composite.pine`
- `Alpha_05_Risk_Exit_Lab.pine`
- `Alpha_06_Strategy_Combination_Lab.pine`

## Institutional Runtime Smoke Test

Use `tradingview/generated/alpha_runtime_smoke_config.json`:

- symbol: `NSE:RELIANCE`;
- chart timeframe: `1D`;
- trend timeframe: `1W`;
- structural timeframe: `1M`;
- dates: `2017-01-01` through `2021-12-31`;
- direction: long only;
- pyramiding: `0`;
- confirmed bars only: enabled;
- market-regime proxy: disabled;
- sector proxy: disabled.

Confirm the script loads, the tables render, entries/exits can be evaluated,
and changing chart bars does not generate a runtime error. This is a smoke test,
not a parity claim or a recommendation-quality test.

## Honest Status Record

Record each status separately:

```text
PYTHON_GENERATION_TESTS=PASS|FAIL
PINE_STATIC_VALIDATION=PASS|FAIL
TRADINGVIEW_MANUAL_COMPILATION=PASS|FAIL|USER_VERIFICATION_REQUIRED
TRADINGVIEW_RUNTIME_SMOKE_TEST=PASS|FAIL|USER_VERIFICATION_REQUIRED
```

Never infer either TradingView status from Python or static-validation results.
