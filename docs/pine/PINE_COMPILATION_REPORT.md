# Alpha Pine Suite v1.0.1 Compilation Report

Run date: 2026-07-18

## Automated Results

- `PYTHON_GENERATION_TESTS=PASS`
- focused Pine and TRL suite: 86 passed;
- full Project Alpha suite: 1,793 passed;
- `PINE_STATIC_VALIDATION=PASS`;
- Pine files checked: 27;
- static errors: 0;
- static warnings: 0;
- Ruff: pass;
- mypy: pass;
- package build: pass.

## Generated Strategy Status

| Generated file | Static validation | TradingView compilation | Runtime smoke |
|---|---|---|---|
| `Alpha_01_Component_Audit.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_02_Setup_Comparator.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_03_Institutional_Composite.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_04_Multi_Timeframe_Composite.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_05_Risk_Exit_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_06_Strategy_Combination_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |

## TRL v2.0 Status

| Research laboratory | Static validation | TradingView compilation | Runtime smoke |
|---|---|---|---|
| `Alpha_TRL_01_Indicator_Weight_Ablation_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_TRL_02_Strategy_Combination_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_TRL_03_Stop_Exit_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |
| `Alpha_TRL_04_Multi_Timeframe_Lab.pine` | PASS | USER_VERIFICATION_REQUIRED | USER_VERIFICATION_REQUIRED |

## TradingView Attempt

The complete 257-line Institutional Composite was loaded into TradingView Pine
Editor. Selecting **Add to chart** opened TradingView's sign-in dialog before a
compiler result was produced. No TradingView compilation or runtime pass is
claimed. The remaining generated scripts were not submitted after the same
account gate was established.

The complete TRL Indicator Weight Ablation Lab was also loaded into the Pine v6
editor on 2026-07-18. Invoking compilation opened the same TradingView sign-in
dialog before a compiler result was produced. The untitled script was neither
saved nor published. No manual TRL compile or runtime pass is claimed.

The exact manual protocol and RELIANCE smoke configuration are in
`TRADINGVIEW_MANUAL_COMPILATION_CHECKLIST.md` and
`tradingview/generated/alpha_runtime_smoke_config.json`.

`PRODUCTION_INFLUENCE=false`
