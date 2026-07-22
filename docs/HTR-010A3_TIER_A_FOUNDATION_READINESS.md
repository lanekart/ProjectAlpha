# HTR-010A3 Tier A Foundation Readiness

HTR-010A3 closes material Tier A identity ambiguity before full-market
corporate-action completion. It is candidate-independent and writes only a
diagnostic sidecar and governed artifacts.

## Blocking and non-blocking conflicts

A conflict blocks HTR-010B only when an identity/date or corporate action cannot
be assigned to one governed security. Concurrent series under one official ISIN
do not create that ambiguity because series remains part of the source-row key.
Conflicting official identity evidence is retained and quarantined rather than
resolved using symbol or company-name similarity.

The authority hierarchy is official ISIN and effective-dated identity evidence,
official reorganisation terms, transition circulars, historical masters, active
checkpoints, and finally candles as non-certifying corroboration.

## Bounded lifecycle evidence

Lifecycle gaps preserve earliest and latest possible dates, prior and subsequent
certified states, and separate identity, membership, and tradability effects.
Candles never bridge a lifecycle gap or establish listing, termination, or
suspension.

## 2026 differences

HDFC, ASTRAL, CRISIL, and COX&KINGS are treated as stale historical predecessor
or replaced-ISIN states, not active checkpoint identities. HDFC additionally
preserves its merger-predecessor role. AMIORG is governed by the official
2025-06-02 symbol transition to ACUTAAS. Historical identities remain available
for point-in-time joins; checkpoint parity is not forced.

## Suspension evidence ceiling

The documented NSE-controlled source families provide partial historical
suspension evidence, not a complete effective-dated suspension/restoration set.
This is a permanent known limitation until new official evidence is supplied.
It limits tradability confidence but does not by itself block membership-based
corporate-action association. “No evidence found” never means “never suspended.”

## Daily activity sources

Legacy and UDiFF bhavcopies are governed as reportable-activity sources with
medium confidence. They permit trading-activity evidence and candle computation
when a valid row exists. They prohibit membership, suspension, and termination
inference. Row absence does not prove a missing-data defect, and expected-row
completeness cannot be audited without an explicit all-security file contract.

## Corporate-action join contract

A security/date is admitted when its governed identity is unique, its ISIN is
valid or an official predecessor/successor relation exists, its identity-date is
unambiguous, the action lies within certified or bounded membership, symbol reuse
is resolved, and source lineage is retained. Tradability certification is not
required merely to associate an official action with an identity.

Join states distinguish certified, bounded-membership, tradability-partial,
quarantined conflict, and unresolved identities. Quarantined identities remain
preserved but are explicitly excluded from the certified denominator.

## Readiness and CLI

`READY_FOR_HTR_010B` requires zero blocking Tier A identity-date conflicts, all
five checkpoint differences treated, unique joins for every admitted identity,
formal activity-source semantics, and suspension separated from membership.
`CONDITIONALLY_READY` permits a small, explicit quarantine. `NOT_READY` applies
where wrong-identity assignment can occur silently.

Run `poetry run python -m alpha historical-truth
tier-a-foundation-readiness --help`. Diagnostic filters affect display only and
never restrict acquisition or certification. The command emits 26 deterministic
JSON, CSV, and Markdown artifacts plus a local DuckDB sidecar.

## Known limitations

Historical suspension/restoration evidence remains partial, many historical
cessation dates remain unknown, and bounded membership is not promoted to exact
history. None of these limitations is hidden or inferred from candle absence.

No replay integration, candidate filters, scoring, approval, stops, allocation,
or production policy changes are made.

`PRODUCTION_INFLUENCE=false`
