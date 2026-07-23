# HTR-010B1E1 Report and Interval Integrity

HTR-010B1E1 repairs the final internal-consistency defects exposed by the first HTR-010B1E run.

## Repairs

- Replaces explainable `UNRESOLVED` admission intervals using explicit future validation outcomes and bridge dependencies.
- Gives uncertified bridge dependencies precedence over factor confirmation.
- Maps reference-price, ambiguous, nonmultiplicative, and insufficient-evidence outcomes to explicit governed admission states.
- Recomputes lookback safety, admission quarantine ranges, economic weight, coverage, and population reconciliation after interval repair.
- Removes previously augmented admission rows before re-augmentation to prevent duplicate blocked intervals.
- Rebuilds residual attribution from final bridge-aware validation results instead of stale HTR-010B1C diagnostics.
- Synchronizes admission-quarantined, evidence-quarantined, and unresolved identity counts across executive, readiness, and reconciliation outputs.
- Exposes both `bridge_uncertified_count` and `bridge_uncertified_case_count`.

## Governance

- Official factors remain immutable.
- Raw OHLCV remains immutable.
- Uncertified ISIN and series bridges remain quarantined.
- No benchmark replay is executed.
- No production-policy changes are made.
- `PRODUCTION_INFLUENCE=false`.
