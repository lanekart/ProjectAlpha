# Point-in-Time Historical Universe Foundation v1.0

## Purpose

This diagnostic-only subsystem records what Alpha can prove was tradable on each
historical date. It never substitutes current index constituents or current sector
classifications for missing historical evidence.

`PRODUCTION_INFLUENCE=false`

## Evidence Contract

The foundation separates five questions:

1. Did a permanent security identity exist?
2. Was it listed and unsuspended on the date?
3. Was it a member of a supported index on the date?
4. Which effective-dated sector classification applied?
5. Was corporate-action lineage complete through the date?

Each answer has its own evidence status and confidence. Missing evidence remains
`UNKNOWN`; it does not inherit the latest known value unless an effective interval
explicitly covers the requested date.

## Legacy Materialization

The first materialization uses valid same-day OHLCV rows to prove only that a
symbol was locally observed and tradable that day. It creates provisional,
ticker-keyed identities because the legacy warehouse lacks full-market permanent
identifiers. First and last local observations are retained separately from
official listing and delisting dates.

The legacy rows also omit series and instrument type. The materialized population
therefore contains observed market instruments, including possible debt, ETF, and
other non-equity records. It must not be presented as an equity-eligible Alpha
universe until authoritative instrument classification is attached.

The legacy `sector` column is not used because previous audits established that it
has no authoritative effective-date semantics. Historical Nifty membership is also
left unknown. This makes the output safe from backward current-constituent leakage,
but not yet institutionally complete.

## Commands

```text
poetry run python -m alpha universe build
poetry run python -m alpha universe audit
poetry run python -m alpha universe date --date YYYY-MM-DD
poetry run python -m alpha universe index --index NIFTY500
```

## Outputs

- `universe_membership.parquet`
- `universe_size_by_date.csv`
- `index_membership_changes.csv`
- `sector_history.csv`
- `listing_history.csv`
- `corporate_actions.csv`
- `survivorship_audit.csv`
- `security_master.json`
- `manifest.json`
- `executive_report.md`

## Promotion Constraint

The observed-price universe may support diagnostic replay that does not condition
on index, sector, delisting, or corporate-action completeness. A true Alpha Fund
replay remains blocked until authoritative effective-dated security master, index,
sector, listing/delisting, suspension, and corporate-action sources are ingested.
