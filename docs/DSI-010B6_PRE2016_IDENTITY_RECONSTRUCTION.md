# DSI-010B6 Pre-2016 Identity Reconstruction

## Purpose

DSI-010B6 reconstructs the missing point-in-time identity context required to
apply already-certified corporate-action factors to 2005-2015 candles.

The milestone is research-only:

```text
PRODUCTION_INFLUENCE=false
FULL_BENCHMARK_REPLAYS=0
```

It does not change factors, raw candles, strategies, recommendations, stops,
gates, portfolio policy, or execution policy.

## Signed Population

The implementation validates and consumes the signed DSI-010B5 queue:

- workflow `30447849010`;
- artifact `8723054631`;
- 476 identity/series segments;
- 253,358 action-exposed rows;
- 415 missing official intervals;
- 60 series mismatches;
- one date-outside-interval case.

Checksum validation prevents a different population from entering B6.

## Evidence Hierarchy

A missing-ISIN row may be certified only by:

1. the existing signed DSI-010B1 dated identity bridge; or
2. a B6 interval bounded by authoritative dated checkpoints.

B6 checkpoints may come from:

- an exact-ISIN canonical NSE source row;
- an official NSE corporate-action record;
- an admitted HTR-009A2 official security event;
- an official NSE listing or permitted-to-trade release;
- a dated NSE historical security-master observation.

Every checkpoint retains its source ID, URL, SHA-256, date, symbol, series, and
ISIN.

## Bounded Intervals

An interval is certified only when:

- a matching checkpoint exists on or before the segment;
- a matching checkpoint exists on or after the segment;
- both checkpoints have the same ISIN, symbol, and series;
- no competing identity checkpoint exists between them;
- both source hashes are present.

The engine does not use price behaviour, symbol similarity, or a smoother
adjusted series as identity evidence. An EQ checkpoint cannot certify BE, BL,
IL, partly-paid, warrant, or debt-series rows.

## Official Source Ceiling

NSE's official Capital Market historical-data specification describes monthly
Masters snapshots with:

- ISIN;
- symbol;
- series;
- security name;
- deletion status.

The archive applicable to 2005-2015 is an NSE historical-data subscription
product. Public current MII files begin much later and cannot be projected
backward. When the subscribed monthly snapshots are unavailable, B6 reports
the precise missing lower or upper checkpoint and remains fail-closed.

This is not represented as a price-data defect and is not filled with
third-party mappings.

## Full-Row Reconciliation

B6 reports two distinct populations:

1. action-exposed rows requiring an adjusted-price factor;
2. all canonical 2005-2015 daily candle rows.

An adjusted overlay can improve while the complete historical identity
certificate remains blocked. `ADJUSTED_REPLAY_READY=true` requires both
populations to have zero unresolved identity rows.

## CLI

```bash
poetry run python -m alpha historical-truth \
  complete-pre2016-identity-reconstruction-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --htr009a2-output artifacts/htr009a2_event_sourced_universe \
  --htr010a3-output artifacts/htr010a3_tier_a_foundation_readiness \
  --htr010b-output artifacts/htr010b_complete_corporate_action_dataset \
  --final-b1c-output artifacts/htr010b1c \
  --final-b1e2-output artifacts/htr010b1e2 \
  --signed-b5-output artifacts/dsi010b5_final_official_evidence_closure \
  --start 2005-01-01 \
  --end 2015-12-31 \
  --output artifacts/dsi010b6_pre2016_identity_reconstruction \
  --refresh-sources
```

Use `--verify-only` for immutable-source reuse. It cannot be combined with
`--refresh-sources`.

## Artifacts

B6 writes:

- summary;
- segment resolution ledger;
- identity checkpoint ledger;
- certified interval ledger;
- official source manifest;
- exact remaining blocker ledger;
- full identity certificate;
- adjusted-replay certificate;
- executive report;
- governed adjusted-history DuckDB overlay.

JSON and CSV outputs use stable ordering. Certificates bind source,
population, timeline, unresolved-segment, raw-candle, and adjusted-history
hashes.

## Readiness

Readiness is true only when:

- all 476 signed segments are resolved;
- every canonical row has one governed identity;
- all required adjustment rows are generated;
- no mixed-price-basis identity remains;
- duplicate and invalid adjusted rows are zero;
- the raw candle fingerprint is unchanged.

Unavailable official historical Masters evidence keeps readiness false. No
security or historical period is silently removed from the denominator.
