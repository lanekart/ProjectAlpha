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


## HTW v4.5 integrity audit

Run the deterministic diagnostic audit with an explicit knowledge cutoff:

```bash
poetry run python -m alpha.historical_truth integrity-audit \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --as-of 2026-07-20 \
  --holiday 2026-01-26
```

Repeat `--holiday` for each exchange holiday supported by explicit evidence.
A 404 is never inferred to be a holiday. Past canonical URLs classify as
`archive_missing`; non-canonical URLs as `url_error`; dates on or after the
audit cutoff as `data_not_released`.

The audit exports deterministic JSON, CSV, and Markdown artifacts covering
expected and observed sessions, coverage and missing dates, duplicate securities
and ISINs, OHLC relationships with per-symbol values and violated rules, negative
prices, zero-volume anomalies, staged source-validation results, immutable
snapshot integrity, and replay blockers.

Candle ingestion and evidence completeness are reported separately. Candle replay
readiness means only that the available candle history and immutable snapshots
pass the stated checks. Full-evidence replay readiness remains false until the
separately governed evidence layers are present and audited; the audit neither
fabricates those layers nor silently treats them as complete.


## HTW v4.5.1 series-aware recovery

The canonical archive preserves every official series. Replay integrity is stricter
about semantics:

- same-ISIN observations across different series are legitimate and are not
  duplicate identities;
- a duplicate ISIN means the same ISIN and series map to multiple symbols on the
  same date;
- `T0` close/range differences are retained as
  `T0_CLOSE_RANGE_EXCEPTION` warnings because the auxiliary T+0 series can carry
  close semantics that are not comparable to its observed intraday range;
- every warning or error is persisted in `validation_quarantine` with its source
  date, row, severity, exact values, violated rules, and source checksum;
- an auxiliary-series warning cannot reject an otherwise valid trading session;
- unresolved `EQ` OHLC failures remain replay-blocking errors.

After upgrading, rerun `populate` for the governed range. Existing verified
snapshots are skipped and previously rejected T0-only sessions are recovered
from the immutable raw archives.

## Canonical Replay Bridge

Run the existing canonical benchmark engine from verified immutable Historical Truth
snapshots:

```bash
poetry run python -m alpha benchmark replay \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --start 2026-01-01 \
  --end 2026-07-20
```

The bridge reconciles the requested warehouse sessions with snapshot files, verifies
every snapshot checksum and metadata record, validates candle relationships, and
fails closed when any observed session is missing or invalid. It projects only the
NSE `EQ` series into the replay store. Other series remain preserved as historical
evidence but cannot create duplicate replay securities.

This is a candle-input bridge only. It does not assert historical index or sector
membership, complete corporate-action evidence, or full-evidence replay readiness.
It does not influence production decisions and never fills missing sessions or
securities.

