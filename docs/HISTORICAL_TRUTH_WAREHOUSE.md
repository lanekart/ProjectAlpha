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
archives, checksum capture, deterministic status exports, and CSV integrity checks.
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

Fetch official NSE bhavcopies:

```bash
poetry run python -m alpha.historical_truth fetch \
  --start 2026-07-01 --end 2026-07-20
```

Export manifest status:

```bash
poetry run python -m alpha.historical_truth status
```

Validate an extracted bhavcopy CSV:

```bash
poetry run python -m alpha.historical_truth validate-csv path/to/file.csv
```

## Guardrails

The downloader writes to a temporary `.part` path and atomically moves a complete
payload into the immutable raw archive. Existing raw files are not replaced.
Re-fetching records a fresh checksum observation without mutating the raw file.
HTTP 404 is classified as `UNAVAILABLE`; other transport, filesystem, or empty-file
errors are classified as `FAILED`.

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
