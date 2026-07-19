# Authoritative NSE/BSE Historical Warehouse

## Purpose

Project Alpha v4.1 retains lawfully obtained NSE/BSE source files, validates
them, and publishes reproducible historical evidence through the Market Truth
Engine (MTE). It is a research-data foundation only.

`PRODUCTION_INFLUENCE=false`

The warehouse never changes recommendation, approval, allocation, replay,
learning, or trading policy.

## Architecture

```text
authorised source or attested manual file
                 |
                 v
        acquisition policy guard
                 |
                 v
 content-addressed immutable raw vault
                 |
                 v
 parser -> validation -> quarantine
                 |
                 v
 transactional DuckDB canonical history
                 |
       +---------+----------+
       |                    |
       v                    v
point-in-time identity   corporate actions
       |                    |
       +---------+----------+
                 v
 raw / adjusted / total-return / point-in-time views
                 |
                 v
 weekly, monthly, universe, quality, version manifest
                 |
                 v
  confirmed partitioned-Parquet publication
                 |
                 v
 Market Truth Engine warehouse providers
```

Downstream consumers do not read raw files, DuckDB tables, or Parquet files
directly. They request an explicit evidence mode and dataset version from MTE.

## Source Authorization

The built-in matrix is deliberately conservative:

| Provider | Dataset families | Manual import | Automated acquisition | Redistribution |
|---|---|---:|---:|---:|
| NSE | bhavcopy, securities, corporate actions, calendar, indices, deliverables | `MANUAL_IMPORT_ONLY` with lawful-source attestation | `LICENCE_REQUIRED` | No |
| BSE | bhavcopy, securities, corporate actions, calendar, indices, deliverables | `MANUAL_IMPORT_ONLY` with lawful-source attestation | `LICENCE_REQUIRED` | No |

An operator may add an `AUTHORISED` automated record only with an evidence
reference, effective dates, and internal storage/research/retention rights.
Unknown permission fails closed. Alpha has no redistribution operation.

## Raw Vault

Supported source containers are CSV, text, ZIP containing one safe file, and
GZip. The vault:

- retains the original bytes;
- names records by a content-derived source ID;
- verifies SHA-256 on every reuse;
- deduplicates exact content;
- rejects checksum reuse with conflicting source metadata;
- records schema fingerprints;
- links corrected same-session files with `supersedes_file_id`;
- never overwrites an earlier file;
- maintains an atomic JSON manifest.

Unsafe archive paths and multi-file ambiguity are rejected.

## Canonical Data

Daily equity records use DuckDB decimal columns and retain source file IDs,
record checksums, quality state, confidence, and dataset version. Missing OHLCV
is not imputed. Impossible OHLC relationships, negative values, malformed
volume, and duplicate securities are quarantined.

Identity records are effective-dated. Symbol, series, ISIN, listing,
delisting, suspension, and relisting intervals are resolved against the query
date. The current security master is never used as undocumented historical
evidence.

Corporate actions preserve raw and normalized terms. Incomplete mergers,
demergers, amalgamations, and schemes remain unadjusted. Clear split, reverse
split, bonus, rights, and dividend terms can be adjusted only when their
reconciliation state is `CONFIRMED` or `REVISED`.

Index and deliverable files are retained in source-linked extension tables.
Deliverable data does not overwrite bhavcopy OHLCV.

## Adjustment Safety

Four explicit modes are supported:

- `RAW`: exchange-published values, immutable.
- `ADJUSTED`: ex-post research continuity under a named dividend policy.
- `TOTAL_RETURN`: dividend-aware research history.
- `POINT_IN_TIME`: only bars and announcements known by `as_of`.

Point-in-time snapshots are keyed by adjustment date, so later builds do not
erase earlier replay-safe views. Future bars, announcements, and effective
events are excluded. Every adjusted record identifies its policy version,
corporate-action version, factors, build date, and source event IDs.

## Publication and Versioning

Materialization creates a content-addressed version such as:

```text
MARKET_WAREHOUSE_1.0.0+<12-character-content-hash>
```

The version records raw manifest hash, session range, exchanges, counts,
identity version, corporate-action version, adjustment policy, quality hash,
build time, code commit, and parent. MTE serves only a version that completed
an explicit `warehouse publish --confirm` operation. A materialized but
unpublished version is not queryable as authoritative warehouse truth.

Canonical, adjusted, identity, corporate action, index, deliverable,
aggregate, and universe tables are exported to compressed Parquet. Daily data
is partitioned by exchange and year; adjusted data is additionally partitioned
by mode.

## CLI

```text
poetry run python -m alpha warehouse status
poetry run python -m alpha warehouse authorisations
poetry run python -m alpha warehouse import-file FILE ... --lawfully-obtained
poetry run python -m alpha warehouse import-directory DIRECTORY ... --lawfully-obtained
poetry run python -m alpha warehouse acquire ...
poetry run python -m alpha warehouse backfill DIRECTORY ... --lawfully-obtained
poetry run python -m alpha warehouse update --as-of YYYY-MM-DD
poetry run python -m alpha warehouse resume
poetry run python -m alpha warehouse sessions audit
poetry run python -m alpha warehouse sessions missing
poetry run python -m alpha warehouse sessions coverage
poetry run python -m alpha warehouse coverage
poetry run python -m alpha warehouse universe --date YYYY-MM-DD
poetry run python -m alpha warehouse universe audit
poetry run python -m alpha warehouse identities audit
poetry run python -m alpha warehouse corporate-actions audit
poetry run python -m alpha warehouse adjustments audit
poetry run python -m alpha warehouse quality
poetry run python -m alpha warehouse reconcile-current
poetry run python -m alpha warehouse publish --confirm
poetry run python -m alpha warehouse report
```

Manual imports require `--lawfully-obtained`. Automated acquisition cannot run
under the default `LICENCE_REQUIRED` entries. Publication requires explicit
confirmation and passes component-level quality gates.

## Adding an Authorized Source

1. Record a `SourceAuthorisation` with the exact provider and dataset.
2. Retain documentary evidence outside the warehouse and reference it by ID.
3. Set storage, research, and retention rights explicitly.
4. Keep redistribution false.
5. Register a provider fetcher that returns bytes without bypassing access
   controls.
6. Run the same immutable ingestion pipeline used by manual imports.
7. Audit quality and reconciliation before publication.

## Operational Constraints

- No broker orders or production-policy changes.
- No fabricated downloads or inferred permissions.
- No in-place edits to raw history.
- No future corporate-action leakage into replay evidence.
- No canonical promotion from an incomplete transaction.
- No silent replacement of the legacy 2,466-session store.
- Research outputs must record the exact warehouse version.

