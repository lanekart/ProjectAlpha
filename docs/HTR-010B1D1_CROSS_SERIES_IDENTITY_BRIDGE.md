# HTR-010B1D1 Cross-Series and Identity-Bridge Forensics

## Purpose

HTR-010B1D1 explains B1D cases where no valid same-series continuity pair was
available. It reconstructs explicit pre-event and post-event candle legs across
series and ISIN boundaries without changing official factors or replay admission.

## Command

```bash
poetry run python -m alpha historical-truth \
  factor-transformation-bridge-forensics \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --htr010b-output artifacts/htr010b_complete_corporate_action_dataset \
  --htr010b1d-output artifacts/htr010b1d_factor_transformation_forensics_2026 \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1d1_cross_series_identity_bridge
```

## Classification contract

- `CROSS_SERIES_PAIRING_ARTIFACT`: the closest pre/post candles share an ISIN
  but use different series. The earlier unscoped `series=None` continuity pair
  must not be treated as factor validation.
- `GOVERNED_CROSS_ISIN_BRIDGE_AVAILABLE`: official transition evidence links
  the predecessor and successor identities and permits price comparison.
- `IDENTITY_TRANSITION_NONCOMPARABLE`: transition evidence exists but explicitly
  prohibits multiplicative price comparison.
- `CROSS_ISIN_BRIDGE_UNCERTIFIED`: different ISIN legs were observed without a
  certifying transition in the correct direction.
- `STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT`: a stable same-ISIN,
  same-series pair exists and the B1D selection contract failed to use it.
- `CANDLE_LINEAGE_BRIDGE_MISSING`: no deterministic pre/post pair can be built.

## Governance

- Official factors remain immutable.
- Bridge ranking uses lineage and boundary proximity, never the smallest market
  gap.
- Every case remains excluded from adjusted replay.
- This milestone does not alter B1B validation or admission. Its output chooses
  the next focused validation-policy repair.
- Full benchmark replays remain zero.
- `PRODUCTION_INFLUENCE=false`.
