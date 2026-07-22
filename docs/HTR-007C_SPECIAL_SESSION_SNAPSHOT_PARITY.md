# HTR-007C Special-Session Immutable Snapshot Parity

## Purpose

HTR-007C repairs the immutable-snapshot parity gap exposed after HTR-007B. The
canonical warehouse contained every official 2016-2025 session, but the four
recovered Muhurat dates did not have the immutable snapshots required by the
historical replay boundary.

`PRODUCTION_INFLUENCE=false`

This is a historical-data integrity milestone. It does not change strategies,
signals, approval policy, portfolio behavior, replay rules, or the 200-session
minimum-history requirement.

## Why Replay Failed

Canonical completeness and replay completeness are distinct contracts:

- `daily_candle` proves that canonical candle rows exist for a date.
- An immutable snapshot freezes those rows, metadata, availability, and a
  content checksum for point-in-time replay.

`HistoricalTruthReplayStore` correctly fails closed when any canonical source
date lacks a snapshot. HTR-007C repairs the missing evidence instead of relaxing
that guard.

## Repair Rules

The parity engine derives special-session targets from a checksum-verified,
certified HTR-007 calendar. It never uses a hardcoded Muhurat date list.

For an eligible missing snapshot it:

1. reads canonical candles through `CanonicalPointInTimeWarehouse`;
2. builds through `PointInTimeSnapshotEngine.build`;
3. persists through `PointInTimeSnapshotEngine.persist`;
4. reloads and verifies the stored content checksum; and
5. compares date, exchange, row count, metadata, volume, and every candle with
   canonical state.

Existing files are never overwritten. A present snapshot is loaded, verified,
and reused only when it is identical to canonical evidence. Checksum, metadata,
date, exchange, count, and candle-content disagreements fail closed with typed
failure codes.

Verification-only mode performs no writes. If snapshot persistence fails after
canonical ingestion, canonical rows remain trusted while recovery reports a
snapshot failure and replay remains blocked until a later repair succeeds.

## CLI

Repair absent eligible snapshots:

```bash
poetry run python -m alpha historical-truth special-session-snapshot-repair \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --snapshot-root alpha_data/snapshots \
  --calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --start 2016-01-01 \
  --end 2025-12-31 \
  --output artifacts/htr007c_special_session_snapshot_parity
```

Add repeatable `--date YYYY-MM-DD` options for focused official-session repair.
Add `--verify-only` to prohibit file creation and modification.

## Full-Window Audit

Every run audits all canonical source dates in the requested window and reports:

- expected, present, missing, and invalid snapshots;
- orphan files without canonical dates;
- symbol-count and candle-content mismatches;
- expected, present, and valid official special-session snapshots; and
- one fail-closed parity state.

Parity states are:

- `COMPLETE_SNAPSHOT_PARITY`
- `INCOMPLETE_MISSING_SNAPSHOTS`
- `BLOCKED_INVALID_SNAPSHOTS`
- `BLOCKED_CONFLICTING_SNAPSHOTS`
- `INSUFFICIENT_EVIDENCE`

## Artifacts

The command writes exactly:

- `htr007c_special_session_snapshot_parity.json`
- `htr007c_special_session_snapshot_parity.csv`
- `htr007c_special_session_snapshot_parity.md`
- `htr007c_missing_snapshots.json`
- `htr007c_missing_snapshots.csv`
- `htr007c_snapshot_verification.json`
- `htr007c_snapshot_verification.csv`

JSON keys and record ordering are deterministic. Created snapshot checksums
include the governed snapshot metadata and remain stable on all later reuse and
verification runs.

## Limitations

HTR-007C repairs only official special sessions represented in the certified
calendar. It does not repair unrelated missing snapshots, infer sessions, alter
calendar evidence, change canonical candle values, or implement HTR-008.
