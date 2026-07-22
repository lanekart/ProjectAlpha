# HTR-010A1 Security Population and Interval Repair

## Scope

HTR-010A1 is a candidate-independent research diagnostic. It classifies every
security retained by HTR-010A, repairs interval defects where evidence permits,
and recalculates denominators for explicitly supported populations. It does not
alter canonical candles, replay behavior, scoring, approvals, stops, allocation,
or production policy. `PRODUCTION_INFLUENCE=false`.

## Security Taxonomy

Official NSE master fields take precedence over series heuristics. The taxonomy
distinguishes mainboard and trade-for-trade equity, SME equity, partly paid
equity, ETFs, REITs, InvITs, mutual-fund units, preference shares, rights,
warrants, government securities, debt, temporary series, administrative records,
and explicit unknowns. Every observed census row remains in the evidence book.

## Support Policy

`NSE-CM-SUPPORT-v1.0.0` separates:

- `TIER_A_CORE_EQUITY`: mainboard and trade-for-trade cash equity;
- `SUPPORTED_EQUITY_NON_CORE`: SME and partly paid equity;
- `SUPPORTED_SEPARATE_ASSET_CLASS`: ETF, REIT, and InvIT records;
- `PRESERVED_UNSUPPORTED`: debt, government securities, funds, rights,
  warrants, preference shares, temporary series, and administrative records;
- unknown and conflicting classifications.

Unsupported evidence is preserved but excluded from the equity denominator.

## Census Reconciliation

HTR-008's 6,334 symbols and HTR-010A's 15,428 symbols measure different scopes.
HTR-010A incorporated full Capital Market masters, including instruments with no
canonical candles and non-equity instruments. HTR-010A1 reports counts by source,
instrument, series, observation year, candle presence, and support state rather
than forcing the broader census to match HTR-008.

## Denominator Semantics

An identity interval begins at an official listing or admission date where one
exists. A later checkpoint is never projected backward. An interval ends at an
official removal date, an official active checkpoint, or a clearly labelled
provisional observation bound. First and last candles remain observations and
are not promoted to certified listing or termination dates.

## Interval Repair

Every HTR-010A overlap and gap receives a typed classification. Exact duplicate
intervals may be merged. Valid parallel series remain parallel. Distinct ISINs
are never joined by symbol or name. Unsupported current-master projection is
excluded from the supported denominator. Conflicting evidence remains visible
and blocks certification.

## Boundaries and Suspensions

Listing, readmission, removal, and final-active checkpoint evidence is retained
with source lineage. Current NSE suspension workbooks and official discovery
pages are inventoried. They do not establish complete historical suspension
intervals; missing historical restoration and suspension evidence remains an
explicit tradability blocker.

## Checkpoints and 2026 Universe

Checkpoint parity is calculated separately for each support state. The 2026
equity universe includes only identities supported by an official final
checkpoint at the requested date. Debt, funds, duplicated series, expired
checkpoint projections, and unresolved records are reported separately.

## Persistence

The governed historical warehouse is opened read-only. Derived HTR-010A1 tables
are written to `htr010a1_repair.duckdb` inside the selected artifact directory.
This preserves all HTR-010A evidence and provides backward-compatible queryable
diagnostic tables without mutating the governed source database.

## Certification

Tier A certification requires a governed identity, official classification,
effective-dated symbol and series history, bounded membership, no unresolved
reuse or overlap, and complete lineage. Missing historical suspension evidence
can leave membership certified while tradability remains partial. Readiness for
HTR-010B is fail-closed.

## CLI

```bash
poetry run python -m alpha historical-truth security-population-repair \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --htr010a-output artifacts/htr010a_complete_security_dataset \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010a1_population_interval_repair \
  --refresh-sources
```

Diagnostic filters affect rendered records only. They never restrict source
acquisition or reconstruction.

## Known Limitations

- Only acquired official checkpoints can certify active populations.
- Complete historical suspension and restoration intervals remain unavailable.
- Unresolved gaps and conflicting intervals are retained, never bridged by
  candle continuity alone.
- No benchmark replay is run by this milestone.
