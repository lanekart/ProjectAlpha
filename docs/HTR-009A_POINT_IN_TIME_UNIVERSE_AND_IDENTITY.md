# HTR-009A Point-in-Time Universe and Identity

## Purpose

HTR-009A certifies what can be proven about an NSE Capital Market security's
identity and trading membership on each historical date. It is a diagnostic
historical-truth milestone. It does not change recommendation, approval,
portfolio, execution, replay, or production policy.

`PRODUCTION_INFLUENCE=false`

## Replay Eligibility Is Not Certification

HTR-008 established that the existing observed-market replay is reproducible
and that many histories contain enough valid candles for feature calculation.
That does not prove that the replay population is a complete point-in-time
market universe. A candle proves that a security traded on that date. It does
not prove when the security was listed, whether it was admitted on a date when
it did not trade, whether it was suspended, or when it was delisted.

HTR-009A therefore preserves two distinct claims:

1. **Observed identity evidence:** an official same-day bhavcopy associates a
   symbol, series, and ISIN with a candle.
2. **Universe membership evidence:** a date-specific official security master
   or notice proves listing, trading status, suspension, restoration, or
   delisting.

The first claim never substitutes for the second.

## Official Evidence Boundary

Only bytes from NSE-controlled hosts or a legally authoritative source may be
admitted. Current lists are marked current-only and are never backfilled into
history. Third-party data may help discover an official document but cannot
certify a record.

Raw acquired bytes are immutable under:

```text
alpha_data/raw/nse/security_master/historical/
```

Each file name contains its SHA-256. A sidecar manifest retains the source URL,
retrieval timestamp, content type, redirect chain, parser, effective date, and
checksum. Verification-only mode recalculates the checksum and never uses the
network. Empty, HTML, malformed, wrong-segment, wrong-date, duplicate, and
conflicting records remain visible as rejected evidence.

## Identity Model

The preferred identity key is `exchange + ISIN`. A raw symbol is never a
governed identity. A synthetic identity is prohibited unless an official source
independently establishes the identity and its validity interval.

Every observation receives one primary `IdentityState` and retains secondary
issue codes. Observed same-day bhavcopy identity is provisional until official
validity evidence covers the relevant date. A current master cannot govern
earlier observations.

Identity intervals retain the symbol, series, dates, source ID, evidence type,
confidence, admission status, and issue codes. Bhavcopy-derived ranges are
explicitly labelled `OBSERVED_DATES_ONLY_NOT_CONTINUOUS_VALIDITY`.

## Membership Model

Membership is classified only from explicit boundaries. Supported states
include active trading, temporary suspension, pre-listing, post-delisting,
relisting, unsupported series, unresolved identity, unresolved membership, and
conflicting evidence.

A missing candle never creates a suspension. The last candle never creates a
delisting. A later candle never backfills an earlier listing date.

## Symbol Reuse and Symbol Changes

A same-symbol/different-ISIN history is split into separate identities even when
the date intervals do not overlap. The reuse audit reports the ISINs, observed
intervals, overlap, candle counts, official evidence, candidate counts, and
classification.

A same-ISIN symbol transition is admitted as continuous only when official
symbol-change evidence names the predecessor, successor, and effective date.
Otherwise both observations remain visible and the transition is classified
`SYMBOL_CHANGE_UNRESOLVED`.

## Listing, Delisting, Suspension, and Relisting

The boundary audit compares official dates, where admitted, with the first and
last canonical candle. Missing official history remains unknown. This prevents
quiet-data gaps from becoming fabricated exchange events and retains historical
securities that are absent from a current list.

## Candle Reconciliation

The warehouse is attached read-only. Every scoped candle is classified in SQL
by identity and membership state, then exported as deterministic year/state
aggregates. Source hashes are retained. No OHLCV or canonical identity field is
changed, and unmatched rows are not deleted.

## Point-in-Time and Survivorship Safeguards

- No symbol-only joins.
- No current-universe historical backfill.
- No future listing, symbol, or identity leakage.
- No joining of reused symbols.
- No inferred suspension or delisting.
- No deletion of renamed, ceased, or historically observed identities.
- Unknown evidence remains unknown and blocks certification where required.

## 2026 YTD

The report separately inventories 2026 canonical rows and observed ISINs. They
enter the certified audit window only when the official session calendar,
immutable snapshots, date-specific security master, and identity evidence share
a common supported date. If the certified calendar ends in 2025, 2026 data is
reported but excluded from the certification window.

## Certification

Certification requires all of the following:

- 100% of official sessions have a date-specific admitted security master;
- 100% of supported canonical rows resolve to governed identity intervals;
- no unresolved symbol reuse or symbol changes;
- listing, delisting, suspension, and relisting boundaries are official-backed;
- no conflicting admitted official records.

A majority threshold is deliberately insufficient. The primary state and every
secondary blocker are deterministic and exported in JSON and Markdown.

## CLI

```bash
poetry run python -m alpha historical-truth point-in-time-universe-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --snapshot-root alpha_data/snapshots \
  --start 2016-01-01 \
  --end auto \
  --root alpha_data \
  --output artifacts/htr009a_point_in_time_universe \
  --refresh-sources
```

Filters support `--symbol`, `--isin`, `--year`, `--identity-state`,
`--membership-state`, and `--only-unresolved`. `--verify-only` prohibits source
acquisition and validates immutable reuse.

## Artifacts

HTR-009A writes 30 deterministic JSON, CSV, and Markdown artifacts covering the
executive report, source inventory, identities, intervals, symbol history,
reuse, symbol changes, boundaries, suspensions, memberships, candle
reconciliation, candidate exposure, survivorship, rejected evidence, and the
certification decision.

## Known Limitations

- Public NSE daily MII security-master publication began much later than the
  2016 replay start, so complete 2016-2025 daily coverage may not be available
  through the public archive.
- Current listed-security files do not prove historical membership.
- The canonical `security_identity` and `corporate_action` tables currently do
  not provide governed historical intervals.
- Complete listing, delisting, suspension, relisting, merger, and scheme history
  requires additional official source families.
- Corporate-action price adjustment is intentionally outside HTR-009A.
- Institutional approval diagnosis is intentionally outside HTR-009A.

These limitations are certification blockers, not reasons to infer data.
