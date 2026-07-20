# Historical Truth Warehouse v1

This milestone establishes an immutable, technical-only archive foundation for
Project Alpha.

## Principles

- Official exchange archives are provenance-bearing inputs, not unquestioned truth.
- Raw files are never overwritten.
- Every retrieval is recorded in an append-only JSONL manifest.
- Missing or unsupported files remain explicit `UNAVAILABLE` or `FAILED`.
- Derived indicators are recomputed from point-in-time market data.
- Fundamental evidence is intentionally excluded from this phase.

## Current v1 scope

The first vertical slice supports planning and fetching NSE cash-market bhavcopy
archives, checksum capture, deterministic status exports, CSV integrity checks,
byte-range resume, bounded retries, and job-level continuation.

The design exposes dataset types for delivery, indices, VIX, corporate actions,
security master, and holidays; adapters for those datasets are subsequent slices.

## Storage layout

```text
alpha_data/
  raw/nse/
  raw/bse/
  staging/
  warehouse/
  snapshots/
  derived/
  manifests/archive_manifest.jsonl
```

## Commands

Initialise the warehouse:

```bash
poetry run python -m alpha.historical_truth init
```

Plan a date range without downloading:

```bash
poetry run python -m alpha.historical_truth plan \
  --start 2026-07-01 --end 2026-07-20
```

Fetch or resume official NSE bhavcopies:

```bash
poetry run python -m alpha.historical_truth fetch \
  --start 2026-07-01 --end 2026-07-20
```

Keep previously failed dates unchanged while continuing the rest of the job:

```bash
poetry run python -m alpha.historical_truth fetch \
  --start 2026-07-01 --end 2026-07-20 --no-retry-failed
```

Export manifest status:

```bash
poetry run python -m alpha.historical_truth status
```

Validate an extracted bhavcopy CSV:

```bash
poetry run python -m alpha.historical_truth validate-csv path/to/file.csv
```

## Resumable retrieval rules

The downloader writes to a `.part` path and atomically moves a complete payload
into the immutable raw archive.

- Existing final files are hashed and reused without network access.
- An interrupted `.part` file is preserved.
- The next run sends `Range: bytes=<current-size>-`.
- HTTP 206 is appended only when `Content-Range` starts at the expected offset.
- HTTP 200 means range was ignored, so that file restarts safely from byte zero.
- Invalid range metadata fails closed and leaves the partial file available.
- Transient failures receive bounded retries with backoff.
- Exhausted failures remain `FAILED` and preserve partial bytes for a later run.
- HTTP 404 becomes `UNAVAILABLE` and removes any stale partial file.
- Manifest-confirmed unavailable dates are skipped during resumed date-range jobs.

## Manifest provenance

Each terminal retrieval result is appended to JSONL with:

- exchange and dataset
- trading date
- official source URL
- immutable relative path
- status
- retrieval timestamp
- SHA-256
- byte size
- explicit error text

The manifest is append-only. Status exports reduce it to the latest state for each
exchange, dataset, and trading date.

## Deliberately deferred

- ZIP member validation and extraction
- DuckDB ingestion
- Delivery, index, VIX, security-master, corporate-action, and holiday adapters
- BSE cross-validation
- Corporate-action-adjusted candles
- Daily point-in-time market snapshots
- Discovery Lab replay

These should be added incrementally only after the bhavcopy archive slice passes
local Ruff, mypy, tests, and a small live archive probe.
