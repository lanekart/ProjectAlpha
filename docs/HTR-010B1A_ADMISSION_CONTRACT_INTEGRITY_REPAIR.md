# HTR-010B1A Admission Contract Integrity Repair

HTR-010B1A repairs the input-contract and measurement defects discovered during the first governed HTR-010B1 execution.

## Purpose

The original HTR-010B1 run was deterministic but not decision-ready because:

- HTR-010B exported `raw_rows`, `adjusted_rows`, `valid_from`, and `valid_to`, while HTR-010B1 expected different names and silently defaulted missing values to zero.
- continuity evidence exported ATR-normalized gap fields that the classifier did not read, leaving every suspected factor unresolved.
- replay admission produced one audit-wide row per identity rather than real date segments.
- lookback safety estimated trading sessions with calendar-day multiplication.
- evidence-quarantined and admission-quarantined identities were reported under the same label.

## Repair contract

HTR-010B1A:

1. uses an explicit alias-aware HTR-010B input adapter;
2. raises `InputContractError` when required evidence is absent;
3. reconciles the HTR-010A3 and HTR-010B Tier A identity sets;
4. queries canonical DuckDB candles for observed Tier A row and identity-session weights;
5. reports observed-window economic weight separately from full-history completeness;
6. classifies suspected factors using `raw_gap_atr` and `adjusted_gap_atr`;
7. segments admission at observed NSE session boundaries;
8. calculates lookback resets from observed exchange sessions;
9. separates evidence-quarantined, admission-quarantined, and unresolved-case populations;
10. fails adjusted-replay readiness closed when contracts, historical population, or factor transformations remain defective.

## Command

```bash
poetry run python -m alpha historical-truth adjustment-replay-admission-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --htr010a3-output artifacts/htr010a3_tier_a_foundation_readiness \
  --htr010b-output artifacts/htr010b_complete_corporate_action_dataset \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1a_admission_contract_integrity_repair
```

`--refresh-sources` is rejected because this milestone consumes pinned upstream evidence. `--verify-only` records invocation mode but performs the same deterministic read-only audit.

## Readiness policy

`NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION` is mandatory when any of the following is true:

- the HTR-010B input contract is invalid;
- the observed Tier A denominator is unavailable;
- the requested historical window is not fully represented in DuckDB;
- suspected factors indicate transformation implementation defects;
- factor cases remain unresolved;
- silent mixed price basis exists;
- quarantine economic weight is unmeasured.

Conditional readiness is allowed only after those blockers are absent and explicit adjusted-view quarantine remains.

## Governance

- Raw OHLCV remains immutable.
- Unknown factors are never treated as one.
- No mixed price view is admitted.
- No benchmark replay is executed.
- Candidate IDs, strategy scoring, approvals, stops, and production policy are unchanged.
- `PRODUCTION_INFLUENCE=false`.
