# HTR-010B1D Factor Transformation Forensics

HTR-010B1D diagnoses the residual `IMPLEMENTATION_DEFECT` population produced by HTR-010B1C after governed calendar coverage is complete.

## Purpose

The milestone converts an undifferentiated transformation-defect count into case-level repair recommendations. It does not change official factors, price history, replay admission, scoring, or production policy.

Each case dossier compares:

- the official HTR-010B factor against arithmetic implied by official split, face-value, or bonus terms;
- the current factor convention against its inverse, for diagnosis only;
- the selected series against other observed series for the same ISIN;
- action-session open and close continuity;
- effective, ex, record, announcement, and nearby observed dates;
- same-session factor composition when multiple actions exist;
- canonical duplicate and source-lineage evidence.

## Classifications

Possible outcomes include:

- `FACTOR_ORIENTATION_CONVENTION_MISMATCH`
- `OFFICIAL_TERM_ARITHMETIC_MISMATCH`
- `SERIES_SELECTION_MISMATCH`
- `SERIES_SELECTION_AMBIGUITY`
- `OPEN_PRICE_NOT_REPRESENTATIVE_CLOSE_BASIS_RESTORES`
- `EVENT_DATE_BASIS_MISMATCH`
- `MULTIPLE_ACTION_COMPOSITION_REQUIRED`
- `RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN`
- `THIN_TRADING_CONTINUITY_UNRELIABLE`
- `RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR`
- `UNRESOLVED_TRANSFORMATION_FORENSICS`

All diagnostic alternatives remain non-authoritative until a later governed repair milestone validates them against official evidence.

## Command

```bash
poetry run python -m alpha historical-truth factor-transformation-forensics \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --htr010b-output artifacts/htr010b_complete_corporate_action_dataset \
  --htr010b1c-output artifacts/htr010b1c_observed_2026_after_htr007c \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1d_factor_transformation_forensics_2026
```

## Artifacts

- `htr010b1d_factor_transformation_forensics.json`
- `htr010b1d_factor_transformation_cases.json`
- `htr010b1d_factor_transformation_cases.csv`
- `htr010b1d_executive_report.md`

## Governance

- Official factors are immutable.
- Inverse, cumulative, alternate-series, date-offset, and close-basis calculations are diagnostic only.
- Every audited case remains excluded from adjusted replay.
- Raw OHLCV remains immutable.
- Full benchmark replays: `0`.
- `PRODUCTION_INFLUENCE=false`.
