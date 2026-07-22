# HTR-010A Complete Historical Security Dataset

## Purpose

HTR-010A builds a full-market, candidate-independent identity, membership, and
tradability dataset for the observed NSE Capital Market population. It consumes
governed HTR-007, HTR-009A2, and HTR-009B evidence. It does not alter canonical
candles, replay behavior, scoring, approval, allocation, or trading policy.

`PRODUCTION_INFLUENCE=false`.

## Population Boundary

The census is the deterministic union of canonical candles, admitted security
events, checkpoint masters, and admitted corporate-action records. Candidate,
verdict, setup, gate, and outcome fields are not accepted as acquisition or
certification filters. Delisted, short-lived, unsupported, and non-candidate
securities remain in the census.

## Authoritative Source Boundary

Only NSE-controlled hosts and retained governed evidence may certify identity or
membership. Existing immutable manifests are inventoried and checksum-verified.
Supplemental listing-compliance, circular-archive, suspension, restoration, and
delisting discovery paths are retained with their HTTP result and failure code.
Third-party data cannot certify a record.

Failed discovery is evidence of a source gap, not evidence that no event occurred.
Missing candles are never treated as suspension, listing, or termination proof.

## Stable Identity

Identity authority is applied in this order:

1. Exchange plus valid ISIN.
2. Official predecessor/successor evidence.
3. Official effective-dated symbol, series, or ISIN transitions.
4. A deterministic synthetic identity when no valid ISIN exists.

Synthetic keys include the observed exchange, symbol, series, and date boundary.
They remain unresolved and preserve the reason for synthesis. Raw symbol equality,
name similarity, adjacent prices, and current-master mappings are never sufficient
to merge identities. The same symbol with different ISINs always remains separate.

## Event-Sourced Intervals

HTR-009A2 symbol, series, membership, and tradability intervals are reused as the
official event stream. Missing full-market records receive observed attribute
intervals and unresolved membership intervals. These intervals support diagnosis;
they do not turn candle presence into official listing evidence.

Listing or admission opens membership. Delisting, withdrawal, or termination
closes it. Suspension preserves membership while pausing tradability. Restoration
reopens tradability. Relisting opens a new interval. Name changes do not create a
new identity. HTR-009B predecessor/successor terms are retained separately from
price-adjustment completeness.

## Point-In-Time Universe Query

The DuckDB view `complete_point_in_time_universe` is interval-backed. A historical
date query uses:

```sql
SELECT *
FROM complete_point_in_time_universe
WHERE DATE '2020-03-31' BETWEEN valid_from AND valid_to;
```

It returns identity, symbol, series, ISIN, membership, tradability, source IDs,
and certification state without applying today's universe backward.

## Candle Reconciliation

The `security_candle_reconciliation` view reconciles every canonical row without
rewriting it. The report exports deterministic identity/state aggregates to avoid
duplicating millions of source rows. Supported states include certified,
provisional, suspended, unresolved, conflicting, and unsupported-series rows.

## Security-Session Gaps

Certified calendar sessions are compared with observed security sessions inside
each life-cycle interval. Gaps are classified as suspension, unresolved identity,
non-tradable series, or unexplained internal gap. Weekends and official holidays
are excluded by construction. No gap becomes a suspension or termination without
an official event.

## Certification Tiers

`TIER_A_CERTIFIED` requires a governed identity, official listing or admission,
an official termination boundary or evidenced active state, official symbol and
series history, no unresolved reuse or transition, point-in-time membership, and
source lineage. Other levels are `TIER_A_PARTIAL`,
`IDENTITY_CERTIFIED_MEMBERSHIP_PARTIAL`, `IDENTITY_PARTIAL`, `UNRESOLVED`, and
`CONFLICTING`.

Overall certification is fail-closed. Majority coverage cannot override a material
listing, termination, suspension, transition, reuse, or candle-reconciliation gap.

## 2026 Treatment

The engine inspects the HTR-007 calendar report and governed current-year calendar
sources. It extends the primary cutoff only when the existing calendar engine can
certify every session through the common candle, calendar, and identity-evidence
date. Otherwise, 2026 remains a separate provisional inventory with the precise
calendar blocker. It is never silently omitted.

## CLI

```bash
poetry run python -m alpha historical-truth \
  complete-security-dataset-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report \
    artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --snapshot-root alpha_data/snapshots \
  --root alpha_data \
  --start 2016-01-01 \
  --end auto \
  --output artifacts/htr010a_complete_security_dataset \
  --refresh-sources
```

`--verify-only` reuses the persisted report and does not acquire or mutate evidence.
Symbol, ISIN, year, identity-state, membership-state, unresolved, and conflicting
filters affect rendered diagnostics only. They never limit acquisition or the
underlying certification run.

## Artifacts And Database Objects

The command writes 38 stable JSON, CSV, and Markdown artifacts. The database adds
backward-compatible `*_complete` tables, `security_dataset_certification`, a
persisted report record, and the two derived views. HTR-009 tables and canonical
candles remain unchanged.

## Known Limitations

- Historical NSE suspension and restoration evidence may remain incomplete when
  official archive discovery does not yield machine-readable effective events.
- A current checkpoint corroborates current state but does not prove every earlier
  membership day.
- Candle-only histories remain provisional.
- Unsupported NSE CM series remain visible but are not certified as supported
  equity security types.
- Sector and historical index membership are explicitly outside HTR-010A.
- HTR-010A runs zero full benchmark replays.
