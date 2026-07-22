# HTR-010A2 Lifecycle and Security-Session Semantics

HTR-010A2 is a candidate-independent research certification layer. It writes a
diagnostic sidecar and deterministic artifacts. It does not alter the historical
truth warehouse, canonical candles, replay, scoring, approval, stops, portfolio,
or production policy.

## Certification contract

Every identity receives exactly one mutually exclusive primary state. Evidence
limitations are separate, overlapping issue flags. Issue counts therefore must
not be added to estimate a population. Full-census and Tier A reconciliation
equations are exported explicitly.

## Canonical observations

All source observations remain preserved. One deterministic canonical
observation is selected per identity using identity certainty, source support,
and observation coverage. Every other record is classified and linked through a
duplicate group. Conflicting facts remain visible; deduplication is not deletion.

## Lifecycle intervals

The sidecar records identity validity, symbol, series, ISIN, market membership,
tradability, suspension, termination, relisting, and predecessor/successor
semantics where evidence exists. Identical intervals may collapse while retaining
lineage. Different ISINs and legitimate parallel series are never merged.
Contradictions and bounded unknown dates remain explicit. Current checkpoints are
not projected backward.

First and last candles are observational bounds only. They do not certify listing
or termination dates. An identity active at the final official checkpoint is not
classified as missing termination evidence.

## Security-session meanings

- Membership: the identity was an official market member.
- Tradability: it was permitted to trade and not known to be suspended.
- Expected source row: the official file contract requires a row.
- Observed source row: a valid canonical row exists.
- Trading activity: the source reports actual trading.
- Candle computability: OHLC fields support indicator calculation.

The legacy CM and UDiFF files expose traded-quantity fields, and the canonical
warehouse has no zero-volume rows. HTR-010A2 therefore classifies them as
reportable-activity sources with medium confidence. This is not proof that every
absence means no trade: historical suspended-security behavior and complete
official row-contract documentation remain unavailable.

## Missing sessions and suspension evidence

An absent activity row is not a market-data gap unless the source contract
guarantees a row. Missing sessions are classified separately as no expected row,
no reported activity, suspension, archive failure, invalid source, validation
rejection, identity failure, true expected-row omission, or unresolved semantics.

The current suspended-security workbook cannot certify complete historical
suspension/restoration intervals. “No evidence found” never means “never
suspended.” Discovery attempts, checksums, failures, and the evidence ceiling are
retained.

## 2026 and HTR-010B readiness

Derived 2026 Tier A identities are reconciled against the final official
checkpoint. Additions and removals require effective-dated evidence; parity is
not forced. HTR-010B readiness is fail-closed and requires unambiguous Tier A
identity-date assignment, known source semantics, separated session concepts,
explained checkpoint differences, and an unchanged candle fingerprint.

## CLI and artifacts

Run `poetry run python -m alpha historical-truth
lifecycle-session-semantics-certify --help`. The command supports acquisition,
verification-only reuse, and diagnostic filters. Filters only affect display;
they never restrict certification.

The command emits the 36 governed JSON, CSV, and Markdown artifacts specified by
HTR-010A2 plus `htr010a2_lifecycle.duckdb`. Large evidence remains local under the
ignored `artifacts/htr010a2_*` paths.

## Known limitations

Official historical suspension intervals, comprehensive effective-dated listing
and termination evidence, and fully documented daily-row semantics remain
incomplete. HTR-010A2 reports those limits rather than inferring state from candle
continuity.

`PRODUCTION_INFLUENCE=false`
