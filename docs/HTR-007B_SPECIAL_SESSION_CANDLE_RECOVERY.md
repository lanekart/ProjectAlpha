# HTR-007B Historical Muhurat Session Candle Recovery

## Purpose

HTR-007B recovers missing NSE Capital Market candles for dates already proven by
the governed HTR-007 calendar to be official special sessions. It is a focused
historical-data repair workflow and has no production influence.

`PRODUCTION_INFLUENCE=false`

The workflow does not maintain its own date list. By default it selects only
calendar records that have both:

- `classification=special_session`; and
- `MISSING_OFFICIAL_SPECIAL_SESSION` in their issue codes.

An ordinary weekend is therefore never admitted merely because candle-like data
exists for it.

## Governed Workflow

Run:

```bash
poetry run python -m alpha historical-truth special-session-candle-recover \
  --calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --output artifacts/htr007b_special_session_recovery
```

Use repeatable `--date YYYY-MM-DD` options only to restrict diagnostics to dates
that are already classified as special sessions by the supplied calendar report.
Use `--refresh` to compare a fresh official response with the immutable trusted
archive; differing bytes fail closed.

## Evidence Boundary

The recovery client accepts downloads only from `nseindia.com` or its
subdomains. It retains:

- the original ZIP archive with its SHA-256 in the filename;
- the untouched extracted CSV;
- a deterministic normalized derivative;
- an immutable acquisition manifest;
- row-level source and canonical-ingestion lineage; and
- validation, ingestion, and recovery audit reports.

The source archive is never replaced by normalized output. Cached evidence is
reused only after checksum verification.

## Validation and Ingestion

Before canonical ingestion, HTR-007B verifies:

- archive and member filenames identify the intended session;
- exactly one safe CSV member exists;
- every row belongs to the intended trading date;
- no adjacent or mixed trading dates exist;
- the file uses a governed NSE Capital Market schema;
- symbols and series are valid;
- OHLC relationships are possible;
- prices and volume are non-negative; and
- symbol/series rows are unique.

Canonical ingestion compares the complete incoming date against existing rows
before opening its write transaction. Identical rows are reused. Any differing
OHLCV or incompatible identity fails closed, and no existing row is overwritten.

## Outputs

The output directory contains exactly these governed reports:

- `htr007b_special_session_recovery.json`
- `htr007b_special_session_recovery.csv`
- `htr007b_special_session_recovery.md`
- `htr007b_special_session_validation.json`
- `htr007b_special_session_validation.csv`
- `htr007b_special_session_ingestion.json`
- `htr007b_special_session_ingestion.csv`

After successful ingestion, rebuild the HTR-007 calendar from canonical
observations. Certification is determined by that independent reconciliation;
the recovery engine cannot edit or certify a calendar report directly.

## Failure Policy

Network, format, checksum, date, identity, candle, and canonical conflicts use
typed failure codes. Partial recovery is reported per session and exits nonzero.
Unknown or conflicting evidence remains unresolved. No synthetic candles,
third-party prices, calendar-policy changes, or manual database inserts are
permitted by this workflow.
