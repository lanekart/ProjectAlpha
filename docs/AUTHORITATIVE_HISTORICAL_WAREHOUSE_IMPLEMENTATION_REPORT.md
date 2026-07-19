# Project Alpha v4.1 Implementation Report

## Outcome

The authoritative historical warehouse is implemented beneath MTE with
immutable source retention, fail-closed authorization, transactional canonical
storage, point-in-time identity and adjustment models, deterministic
aggregation, universe snapshots, quality diagnostics, legacy reconciliation,
versioned Parquet publication, and warehouse-backed MTE providers.

`PRODUCTION_INFLUENCE=false`

No recommendation, approval, replay, learning, allocation, live market-data,
order, or trading policy was changed.

## Storage

- DuckDB canonical and metadata store: `data/market_truth/warehouse.duckdb`
- Immutable source vault: `data/market_truth/raw/<exchange>/<dataset>/<year>/...`
- Raw manifest: `data/market_truth/metadata/raw_manifest.json`
- Authorization registry: `data/market_truth/metadata/source_authorisations.json`
- Versioned Parquet: `data/market_truth/publications/<dataset-version>/...`
- Parquet compression: Zstandard
- Daily partitions: exchange/year
- Adjusted partitions: mode/exchange/year

## Source Authorization Matrix

All default NSE/BSE automated entries are `LICENCE_REQUIRED`. All default
manual entries are `MANUAL_IMPORT_ONLY` and require an explicit lawful-source
attestation. Internal storage, research, and retention are recorded separately.
Redistribution is disabled for every source.

## Archive Types

Implemented and tested:

- uncompressed CSV and text;
- ZIP with one safe payload;
- GZip;
- NSE legacy and UDiFF-compatible daily aliases;
- BSE daily field aliases;
- security masters;
- corporate actions;
- exchange calendars;
- index daily history;
- deliverable quantity/percentage extensions.

## Current Workspace Evidence

The v4.1 warehouse starts empty because Alpha cannot attest the legal basis of
files on the user's behalf.

| Metric | Current authoritative warehouse |
|---|---:|
| NSE sessions | 0 |
| BSE sessions | 0 |
| Securities | 0 |
| Daily rows | 0 |
| Corporate actions | 0 |
| Adjusted rows | 0 |
| Quarantined rows | 0 |
| Published dataset version | unavailable |

The existing local store remains unchanged:

- 2,466 sessions;
- 2016-07-08 through 2026-07-10;
- 4,898,586 daily rows;
- 5,340 symbols;
- prior confidence label: 90%.

These figures are a reconciliation baseline, not v4.1-authoritative coverage.
No warehouse promotion occurs until lawfully sourced files are imported,
audited, reconciled, materialized, and explicitly published.

## Deterministic Fixture Evidence

The regression fixture proves all three required history modes.

### RELIANCE raw

| Date | Open | High | Low | Close | Volume |
|---|---:|---:|---:|---:|---:|
| 2020-01-01 | 100 | 101 | 99 | 100 | 1,000 |
| 2020-01-02 | 100 | 102 | 99 | 100 | 1,100 |
| 2020-01-03 | 50 | 53 | 49 | 52 | 1,200 |

### RELIANCE adjusted

With a confirmed 2:1 split effective 2020-01-03, pre-event prices are halved
and pre-event volume is doubled. The raw rows remain byte- and value-identical.
Additional confirmed bonus, rights, and explicit dividend policies are tested;
an incomplete merger is skipped.

### RELIANCE point-in-time

At `as_of=2020-01-01`, only the 2020-01-01 bar is present and the split factor
is 1. At `as_of=2020-01-03`, the announcement and effective event are eligible,
and the split source event is recorded. No future bar or announcement is
visible in the earlier snapshot.

### Symbol continuity

The identity fixture resolves `OLDCO` during 2020 and `NEWCO` during 2021 to
the same `SEC-1` continuity ID. The ISIN change from `INEOLD` to `INENEW` is
retained and surfaced by the identity audit.

### Aggregates

The fixture weekly/monthly aggregate is deterministic:

- open: 100;
- high: 102;
- low: 49;
- close: 52;
- volume: 3,300;
- session count: 3.

## Quality and Reconciliation

Separate quality components report:

- archive checksum integrity;
- schema consistency;
- OHLC structure;
- previous-close chains;
- point-in-time identity coverage;
- unexplained price gaps;
- adjustment-factor continuity;
- session completeness.

The legacy reconciler reports session and symbol overlap, matching rows, OHLCV
differences, identity differences, corporate-action-linked differences,
unexplained differences, and quarantine candidates. It opens the legacy store
read-only and never replaces it.

## MTE Providers

After confirmed publication MTE registers:

- `NSE_BSE_RAW_WAREHOUSE`;
- `NSE_BSE_ADJUSTED_WAREHOUSE`;
- `NSE_BSE_TOTAL_RETURN_WAREHOUSE`;
- `NSE_BSE_POINT_IN_TIME_WAREHOUSE`.

The raw provider also exposes identity, corporate actions, calendar, universe,
and index observations. Providers remain absent when no warehouse database is
present and refuse materialized-but-unpublished versions.

## Regression Coverage

Deterministic tests cover authorization denial, authorized automation, manual
attestation, checksums, ZIP custody, duplicate imports, corrections,
supersession, malformed rows, schema changes, NSE/BSE daily parsing, calendar,
index and deliverable extensions, session coverage, symbol/ISIN continuity,
listings, delistings, suspensions, split/bonus/rights/dividend adjustments,
incomplete mergers, raw immutability, point-in-time safety, weekly/monthly
aggregation, universe snapshots, restart visibility, versioning, publication,
MTE compatibility, legacy reconciliation, JSON/CSV, CLI rendering, and policy
isolation.

## Quality Gates

- Full pytest suite: 1,706 passed.
- Ruff: passed.
- mypy: passed across 530 source files.
- Poetry source and wheel build: passed.

The authoritative workspace warehouse currently remains unpublished and
therefore unavailable to MTE as a configured evidence provider. This is the
intended fail-closed result until lawful files and their authorization evidence
are supplied.
