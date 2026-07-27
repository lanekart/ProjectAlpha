# DSI-010 — Pre-2011 Official Calendar Recovery

## Purpose

This workflow recovers official NSE trading-calendar documents for calendar years
2005 through 2010. It records every transport attempt, verifies document identity,
extracts and validates circular text, preserves segment scope, and produces
reviewable evidence files without inferring holidays or special sessions from
candle presence, candle absence, or archive HTTP status.

The workflow remains diagnostic and fail-closed.

## Candidate registry

Recovery begins from an operator-reviewed JSON registry:

```json
{
  "candidates": [
    {
      "year": 2010,
      "source_id": "NSE_CM_2010_CALENDAR",
      "source_url": "https://nsearchives.nseindia.com/content/circulars/example.pdf",
      "segment_scope": "CAPITAL_MARKET",
      "expected_sha256": null,
      "expected_download_number": null,
      "expected_circular_date": null,
      "expected_subject": "trading holidays",
      "requires_muhurat_statement": true
    }
  ]
}
```

Only HTTPS URLs on governed NSE domains are accepted. Third-party sources may be
used to discover an official candidate URL, but cannot enter the candidate
registry as authoritative evidence.

## Recovery command

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2011-calendar-source-recovery \
  --candidate-registry artifacts/dsi010_pre2011_candidates.json \
  --output artifacts/dsi010_pre2011_official_sources
```

The command records:

- requested and final URL;
- HTTP status and content type;
- byte size and SHA-256;
- PDF-signature validation;
- deterministic text-extraction status;
- exchange, segment, subject, year, circular-number, circular-date, holiday-table,
  and Muhurat-statement checks;
- duplicate-document detection by SHA-256;
- accepted, partial, or rejected recovery state.

An HTTP 200 response is accepted only when it contains either a valid PDF or an
official archive HTML document whose URL also ends in `.htm`/`.html`, and all mandatory
circular-content checks pass. HTML returned for a PDF URL remains rejected.

## Segment boundary

Capital Market or explicit exchange-wide evidence may become a fully verified
source after manual review. F&O or other cross-segment evidence remains
`PARTIALLY_VERIFIED_OFFICIAL_EVIDENCE` and cannot certify a Capital Market
session by itself.

The final calendar certifier requires `CAPITAL_MARKET` or `EXCHANGE_WIDE` scope.

## Reviewed source build

After an accepted document is manually reviewed, create a CSV with:

```csv
trading_date,classification,description,review_state,segment_scope,source_id
```

Allowed classifications are `HOLIDAY` and `SPECIAL_SESSION`. Accepted rows must
use `VERIFIED_OFFICIAL_EVIDENCE` and must trace to the source identity.

Build the governed source:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-calendar-source-build \
  --review-csv reviewed_calendar.csv \
  --source-document official_source.pdf \
  --extracted-text extracted_text.txt \
  --content-validation content_validation.txt \
  --source-url https://nsearchives.nseindia.com/content/circulars/example.pdf \
  --source-id NSE_CM_2010_CALENDAR \
  --covered-year 2010 \
  --segment-scope CAPITAL_MARKET \
  --output nse_2010_official_calendar.json
```

The resulting JSON binds the source document, reviewed CSV, extracted text, and
content-validation record by path and SHA-256. Any later hash mismatch fails
closed.

## Required artifacts

The recovery directory contains:

- `source_candidate_attempts.csv`;
- `source_candidate_attempts.json`;
- `source_recovery_summary.json`;
- `source_recovery_summary.md`;
- `evidence_hashes.txt`;
- immutable downloaded documents;
- deterministic extracted text.

Reviewed annual source files and review ledgers are separate governed artifacts.

## Certification boundary

Recovery success does not itself certify the 2005–2015 calendar. Certification
remains blocked until:

- every year from 2005 through 2015 has sufficient official Capital Market or
  exchange-wide evidence;
- all accepted files and review ledgers validate against their recorded hashes;
- all calendar rows are manually reviewed;
- unresolved weekdays, conflicts, missing special sessions, and unconfirmed
  special sessions are zero;
- no classification was inferred from archive status or observed candles.

```text
CALENDAR_CERTIFICATION_PERMITTED=false
PRODUCTION_INFLUENCE=false
```
