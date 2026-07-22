# HTR-009A2 Event-Sourced Point-in-Time Universe

## Purpose

HTR-009A2 reconstructs historical NSE membership and tradability from official
checkpoint masters and effective-dated security events. It removes the HTR-009A
assumption that every certified session requires its own archived full security
master. It does not relax evidence requirements and has no production influence.

`PRODUCTION_INFLUENCE=false`

## Evidence Boundary

Only official NSE-controlled hosts can supply admitted event evidence. Raw source
bytes are stored immutably below:

`alpha_data/raw/nse/security_events/historical/`

Each file name includes its SHA-256 checksum. A sidecar manifest retains the
source URL, retrieval timestamp, redirects, response metadata, parser, record
counts, and failure details. Verification-only mode reuses those bytes and
rejects a checksum mismatch. It performs no network acquisition and no database
mutation.

Third-party material may locate an official document, but it cannot certify an
event. A candle can reveal a possible source gap or contradiction; it cannot
establish listing, suspension, delisting, or identity continuity.

## Event Contract

The immutable event ledger represents listing and admission, identity changes,
suspension and restoration, termination, and reorganisation events. Every event
retains:

- deterministic event ID;
- effective and announcement dates;
- old and new symbol, series, and ISIN values;
- predecessor and successor identities;
- separate membership and tradability effects;
- official source and document location;
- admission and confidence states.

Ambiguous rows are provisional or rejected. Conflicting effects for the same
identity and effective date are marked `CONFLICTING` and block certification.

## Reconstruction Rules

1. Listing or admission opens membership and tradability.
2. Suspension closes tradability without closing membership.
3. Revocation or restoration reopens tradability.
4. Delisting, withdrawal, or identity termination closes membership.
5. Symbol and series changes create adjacent attribute intervals.
6. Name changes retain the same identity unless official evidence says otherwise.
7. A different ISIN creates a separate identity or explicit successor link.
8. A later checkpoint corroborates an open interval through its checkpoint date.
9. An open interval without a terminating event or later checkpoint remains
   `UNRESOLVED_NO_TERMINATION_EVIDENCE`.
10. Current checkpoint membership is never projected backward without an official
    listing or admission boundary.

Membership and tradability are persisted in separate governed tables. This keeps
a suspended listed security distinct from a delisted security.

## Checkpoint Reconciliation

For each official checkpoint, the engine compares the event-derived universe to
the master without rewriting the event ledger. It reports missing and unexpected
identities plus symbol, ISIN, series, and status mismatches. Any material mismatch
is visible in the report and blocks full certification.

## Database Tables

HTR-009A2 adds backward-compatible tables:

- `security_event`
- `security_event_lineage`
- `security_identity_relationship`
- `security_symbol_interval`
- `security_series_interval`
- `security_name_interval`
- `security_membership_interval`
- `security_tradability_interval`
- `security_event_rejection`
- `security_checkpoint_reconciliation`

The migration does not delete or replace HTR-009A tables, candle data, raw source
evidence, snapshots, benchmark outputs, or ledgers.

## Certification

Full certification requires official listing evidence, corroborated open
boundaries, complete suspension/restoration evidence, complete identity
transitions, resolved symbol reuse, checkpoint parity, and no conflicting
official evidence. Partial evidence produces `PARTIALLY_CERTIFIED` with every
secondary blocker listed.

The engine reports 2026 YTD separately. It does not certify 2026 unless the
official session calendar and event/master evidence both reach the selected
canonical cutoff.

## CLI

Acquire or refresh official event evidence and run certification:

```bash
poetry run python -m alpha historical-truth \
  event-sourced-universe-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report \
    artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --root alpha_data \
  --start 2016-01-01 \
  --end auto \
  --output artifacts/htr009a2_event_sourced_universe \
  --refresh-sources
```

Verify immutable reuse without acquisition or database mutation:

```bash
poetry run python -m alpha historical-truth \
  event-sourced-universe-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --calendar-report \
    artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --root alpha_data \
  --start 2016-01-01 \
  --end auto \
  --output artifacts/htr009a2_event_sourced_universe_reuse_audit \
  --verify-only
```

Filters include `--symbol`, `--isin`, `--year`, `--event-type`,
`--membership-state`, and `--only-unresolved`. Filters change diagnostic exports
only; they never change production behavior.

## Governance

- No recommendation, signal, approval, allocation, replay, or trading policy is
  changed.
- No broker or order API is called.
- No full benchmark is run unless a non-empty certified date window creates a
  meaningful certified candidate-exposure change.
- Missing evidence remains missing.
- Source bytes and frozen HTR-009A baseline hashes make every result auditable.

