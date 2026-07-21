# HTR-005 — Governed Historical Research Replay

## Objective

HTR-005 makes HTR-004 canonical replay mandatory for Project Alpha's primary
historical observation and replay entrypoints. Historical decisions and outcome
records must not be built directly from raw ticker-based OHLCV frames.

This milestone changes historical-truth fidelity and provenance only. It does
not change strategy logic, recommendation thresholds, approval policy,
portfolio policy, or broker behavior.

## Governed input artifacts

Every governed replay run requires two explicit recovery artifacts:

1. **HTR-002 canonical security identities**
   - CSV, JSON, or JSONL.
   - Required fields: `security_id`, `symbol`.
   - Optional fields: `exchange`, effective dates, historical symbols,
     evidence IDs, and recovery version.
2. **HTR-003 canonical corporate-action timeline**
   - CSV, JSON, or JSONL.
   - May contain zero events, but the artifact itself must exist.
   - Resolved price actions require governed factors.
   - Unresolved material actions remain present and cause affected replay
     observations to fail closed.

The loader hashes both files and records their paths, SHA-256 digests, record
counts, stable security IDs, and unresolved action IDs in
`governed_replay_inputs.json`.

Symbol-change events enrich the HTR-002 identity timeline with historical ticker
aliases. Missing row-level evidence is not invented; file-level hashes provide
artifact lineage when row evidence is absent.

## Point-in-time semantics

The governed price repository applies these cutoffs:

- `find_by_trade_date(D)`: `as_of = D`.
- `find_history_by_symbols(..., end_date=D)`: `as_of = D`.
- `find_range_by_symbols(..., end_date=D)`: `as_of = D`.

Decision-day prices and historical decision inputs therefore cannot use actions
announced after the replay date. Outcome frames begin after the replay date and
use the outcome window's end date as their measurement cutoff.

Each source session is canonicalized independently. The released frame includes:

- stable `security_id`;
- raw and canonical symbols;
- raw and adjusted OHLCV;
- cumulative price and volume factors;
- applied and unresolved event IDs;
- replay status and recovery version;
- canonical snapshot and consumer-frame SHA-256 values; and
- an enforced consumer contract marker.

## Fail-closed conditions

Governed replay rejects:

- missing or unreadable HTR-002/HTR-003 artifacts;
- unresolved requested security identities;
- ambiguous ticker-to-security continuity;
- duplicate stable identities on one trade date;
- invalid or mixed trade dates;
- observations outside the requested range or after `as_of`;
- unresolved material corporate actions affecting the frame;
- frames that already contain canonical governance columns; and
- replay-engine output dates or data cutoffs not covered by the governed
  observation build.

## CLI contract

### One governed replay run

```bash
poetry run python -m alpha replay run \
  --from-date 2025-01-01 \
  --to-date 2025-12-31 \
  --identity-artifact artifacts/security_entity_recovery/canonical_preview.csv \
  --corporate-action-artifact artifacts/corporate_action_recovery/canonical_timeline.csv \
  --output artifacts/governed_historical_replay
```

### Governed replay accumulation

```bash
poetry run python -m alpha replay accumulate \
  --from-date 2020-01-01 \
  --to-date 2025-12-31 \
  --frequency monthly \
  --identity-artifact artifacts/security_entity_recovery/canonical_preview.csv \
  --corporate-action-artifact artifacts/corporate_action_recovery/canonical_timeline.csv \
  --output artifacts/governed_historical_replay_accumulation
```

Each selected replay date receives a separate proof directory.

### Refresh replay before combination analysis

```bash
poetry run python -m alpha learning combinations \
  --refresh-replay \
  --from-date 2025-01-01 \
  --to-date 2025-12-31 \
  --identity-artifact artifacts/security_entity_recovery/canonical_preview.csv \
  --corporate-action-artifact artifacts/corporate_action_recovery/canonical_timeline.csv \
  --replay-output artifacts/governed_historical_replay_refresh
```

`--refresh-replay` fails closed when either governed artifact is absent.

## Output artifacts

A governed run can emit:

- `governed_historical_replay_run.json` — complete deterministic run manifest;
- `governed_replay_inputs.json` — HTR-002/HTR-003 input lineage;
- `governed_replay_reads.csv` — each governed repository read;
- `governed_historical_replay_run.md` — human-readable summary;
- `canonical_replay_attestations.json`;
- `canonical_replay_attestations.csv`; and
- `canonical_replay_attestations.md`.

The run digest excludes wall-clock timestamps and measured runtime because those
values do not alter the decision inputs or replay outputs. It includes recovery
input hashes, repository reads, consumer attestations, observation counts,
replay dates, stable replay-result fields, and contract versions.

## Boundary enforcement

The lower-level `HistoricalObservationFactory` remains an internal construction
utility for focused unit tests and explicitly non-governed diagnostics. Production
observation-building code must use `GovernedHistoricalObservationFactory` or
`GovernedHistoricalReplayService`.

A source-boundary regression test scans `alpha/` and fails if a new production
module constructs `HistoricalObservationFactory` directly. The primary replay
CLI is also checked for direct raw factory or replay-engine construction.

## Non-goals

HTR-005 does not:

- acquire new market data;
- infer missing merger, demerger, rights, or other action economics;
- tune strategies, indicators, thresholds, or approval gates;
- change live execution or broker integration; or
- claim that every diagnostic price query in Project Alpha is a governed replay
  decision path.
