# HTR-010B1D2 Bridge-Aware Factor Validation Repair

HTR-010B1D2 corrects the diagnostic disposition of the residual 2026 factor cases after HTR-010B1D1 reconstructed explicit pre/post candle bridges.

## Purpose

The milestone separates two questions that earlier audits conflated:

1. Does the official factor restore price continuity on the reconstructed candle pair?
2. Is the series or ISIN bridge officially certified for adjusted replay?

A factor may be confirmed while the bridge remains quarantined.

## Inputs

- `htr010b1d1_bridge_cases.json`
- requested audit start and end dates

## Corrected dispositions

- `FACTOR_CONFIRMED_ON_STABLE_SECURITY_PAIR`
- `FACTOR_CONFIRMED_VIA_SAME_SESSION_COMPOSITE`
- `FACTOR_CONFIRMED_ON_UNCERTIFIED_CROSS_ISIN_BRIDGE`
- `FACTOR_CONFIRMED_ON_UNCERTIFIED_CROSS_SERIES_BRIDGE`
- `RAW_CONTINUITY_ALREADY_PRESENT_FACTOR_NOT_VALIDATED`
- `FACTOR_INSUFFICIENT_STABLE_PAIR_CONTEXT`
- `FACTOR_INSUFFICIENT_COMPOSITE_CANDLE_CONTEXT`
- `FACTOR_INSUFFICIENT_BRIDGE_CANDLE_CONTEXT`
- `FACTOR_NOT_CONFIRMED_AFTER_BRIDGE_REPAIR`

## Contracts

- Same-session split and bonus factors are evaluated as one diagnostic composite.
- Individual factors are never mutated or replaced by the composite.
- Cross-ISIN and cross-series factor confirmation does not certify the bridge.
- Raw continuity already within threshold cannot be reclassified as a factor-orientation defect merely because the inverse transform also falls within threshold.
- Missing ATR or boundary candles becomes insufficient evidence, not an implementation defect.
- No case is admitted to replay by this milestone.
- `PRODUCTION_INFLUENCE=false`.

## Command

```bash
poetry run python -m alpha historical-truth \
  bridge-aware-factor-validation-repair \
  --htr010b1d1-output artifacts/htr010b1d1_cross_series_identity_bridge_2026 \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1d2_bridge_aware_validation_repair_2026
```

## Artifacts

- `htr010b1d2_validation_repair.json`
- `htr010b1d2_reclassified_cases.json`
- `htr010b1d2_reclassified_cases.csv`
- `htr010b1d2_same_session_groups.json`
- `htr010b1d2_executive_report.md`

The output is diagnostic evidence for the later B1B validation-policy repair. It does not change the existing HTR-010B1C report, official factors, quarantine intervals, or production consumers.
