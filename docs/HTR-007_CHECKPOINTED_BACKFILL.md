# HTR-007 Checkpointed NSE Backfill

## Purpose

HTR-007 Slice 2 executes the NSE cash-market bhavcopy population window through the existing governed Historical Truth Warehouse. It coordinates official archive planning, bounded concurrent downloads, immutable raw-file verification, validation, DuckDB ingestion, point-in-time snapshot generation, restart checkpoints, and deterministic run artifacts.

This slice is operational population only. It does **not** certify the official trading calendar or research readiness.

## Governance boundary

Every report is fixed to:

- Planning basis: `WEEKDAY_CANDIDATES_UNRECONCILED`.
- Certification state: `unreconciled_not_certified`.

A weekday candidate that returns an official archive `404` is recorded as `unavailable`; it is not silently removed and is not automatically classified as an exchange holiday. Special sessions are also not inferred by this slice. Official session reconciliation belongs to HTR-007 Slice 3 and final certification belongs to Slice 4.

## Operational command

```bash
poetry run python -m alpha.historical_truth.backfill_cli run \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --root alpha_data \
  --output-dir artifacts/htr007_backfill \
  --workers 4
```

Use `--no-retry-failed` to preserve and skip a previously failed download task during a restart. Failed task state is restored from the download checkpoint rather than reset to pending.

## Checkpoints

For a window such as `2016-01-01` through `2026-07-20`, the engine writes:

```text
alpha_data/manifests/htr007_backfill_2016-01-01_2026-07-20.json
alpha_data/manifests/htr007_backfill_2016-01-01_2026-07-20_downloads.json
```

The run checkpoint records deterministic per-date population state. The download checkpoint records attempts and task states. Both are written through temporary files and atomic replacement.

An existing run checkpoint must match the contract version, requested window, planning basis, and certification state. A mismatch blocks execution.

## Immutable raw archive rule

When a raw archive already exists and a previously trusted `downloaded` or `validated` manifest digest is available, the file must match that digest. Checksum drift blocks the date before population.

When a missing raw archive is refetched but its checksum differs from a trusted historical digest, the new file is moved to the quarantine tree and the request is recorded as failed. It is never silently installed over the governed raw path.

## Per-date states

- `complete`: canonical snapshot exists and verifies successfully.
- `unavailable`: the official archive explicitly reported the candidate date unavailable.
- `failed`: download, immutable checksum, ZIP, schema, OHLCV, ingestion, or snapshot verification failed.
- `skipped`: a restored failed task was not retried because `--no-retry-failed` was selected.
- `deferred`: only used by the programmatic bounded-run test hook; normal CLI runs do not defer records.

`operationally_complete` means every candidate date was explicitly resolved as complete or unavailable, with no failed, skipped, or deferred records. It does not mean certified.

## Artifacts

The output directory contains:

```text
htr007_backfill.json
htr007_backfill.csv
htr007_backfill.md
```

The JSON report includes a deterministic SHA-256 over the versioned run contract and all per-date records. Absolute local snapshot paths are not included in the digest; paths are stored relative to the warehouse root when possible.

## Restart procedure

Rerun the identical command. Completed downloads retain their attempt counts, valid immutable snapshots are reused, interrupted download tasks reset to pending, and unresolved failures follow the selected retry policy.

Changing the requested date window creates a distinct checkpoint pair. Do not rename or copy a checkpoint to a different window.

## CI policy

CI performs no live NSE download. Tests create deterministic local legacy and UDiFF ZIP fixtures and verify:

- cross-schema population;
- deterministic reruns and artifacts;
- partial-run recovery;
- explicit unavailable evidence;
- restored failed-state handling;
- immutable archive checksum drift blocking;
- CLI behavior and uncertified-state reporting.

## Deferred certification work

Before any authoritative replay-readiness claim, HTR-007 must still populate and reconcile:

- the official trading calendar and special sessions;
- corporate actions and symbol changes;
- listing, suspension, delisting, and stable identity evidence;
- benchmark history;
- annual inventory coverage and final HTR-006 readiness artifacts.
