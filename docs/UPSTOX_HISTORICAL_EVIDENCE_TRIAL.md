# Upstox Historical Evidence Trial

## Purpose

This diagnostic measures Upstox Historical Candle V3 coverage against Project
Alpha's immutable 657-candidate historical-source manifest. It does not add
Upstox to the production provider registry and cannot influence reconstruction,
recommendations, approvals, entry timing, stops, targets, or trading policy.

`PRODUCTION_INFLUENCE=false` is part of every domain result.

## Analytics Token

Set the read-only credential locally:

```bash
UPSTOX_ANALYTICS_TOKEN=
```

The probe reads only this environment variable. It never falls back to
`UPSTOX_ACCESS_TOKEN`, requests an account resource, or calls an order API. The
token is excluded from representations, exceptions, exports, persistence, and
request hashes. Tests use mocked provider responses.

An Analytics Token is preferable for this trial because Upstox documents it as
a read-only token for supported GET and market-data interfaces. The probe still
requires `--live` before making any network request.

## Official Interfaces

Only two HTTPS API path families are permitted by the transport:

- [Instrument Search](https://upstox.com/developer/api-documentation/instrument-search/):
  `GET https://api.upstox.com/v2/instruments/search`
- [Historical Candle Data V3](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/):
  `GET https://api.upstox.com/v3/historical-candle/{instrument_key}/days/1/{to_date}/{from_date}`

The authentication probe uses Instrument Search and a bounded Nifty 50 daily
history request. It does not request profile, funds, holdings, positions, or
orders. Upstox documents the selected market-data endpoints as not requiring a
static IP.

Instrument Search permits 1 through 30 records per page. The probe requests 10,
and the isolated client rejects values outside the documented range before any
network request.

## Commands

```bash
poetry run python -m alpha replay upstox-auth-probe
poetry run python -m alpha replay upstox-auth-probe --live
poetry run python -m alpha replay upstox-historical-sample --dry-run --sample
poetry run python -m alpha replay upstox-historical-sample --live --sample
poetry run python -m alpha replay upstox-historical-coverage
poetry run python -m alpha replay upstox-identity-coverage
poetry run python -m alpha replay upstox-adjustment-audit
poetry run python -m alpha replay upstox-series-integrity
poetry run python -m alpha replay upstox-evidence-report
poetry run python -m alpha replay upstox-full-population-utility
```

The evidence commands support candidate, symbol, year, gap-cause, and limit
filters plus deterministic text, JSON, and CSV output. `--resume` continues a
matching sample checkpoint.

Full-population collection is intentionally harder:

```bash
poetry run python -m alpha replay upstox-historical-coverage \
  --live \
  --full-population \
  --confirm-full-population \
  --resume
```

It is rejected unless a successful sample is already persisted. The run reuses
completed sample evidence, caches repeated symbol searches, checkpoints every
candidate, and resumes a partial full-population dataset deterministically.

## Trial Design

The existing deterministic 30-candidate sample is reused. It contains 2016 and
recent candidates, repeated symbols, active and ended-continuity cases,
corporate-action ambiguity, partial lookbacks, multi-session gaps, liquidity
extremes, multiple setup types, regimes, and entry-timing states. It deliberately
does not select only easy active securities.

The sample is stratified for diagnostic breadth, not randomly sampled. Its
coverage rate is therefore not projected to the full manifest. A projected rate
is emitted only after the complete immutable manifest is tested.

## Identity Rules

Resolution follows this order:

1. existing authoritative instrument key;
2. ISIN;
3. historical symbol with an effective interval;
4. exact Instrument Search result;
5. exact official Upstox instrument-file result;
6. unresolved.

Fuzzy company names are never authoritative. A current-symbol-only match is
rejected for a historical interval without continuity evidence. An exact search
result may be used provisionally to test price availability, but it does not
make identity reconstruction ready.

The current 657-candidate manifest contains internal permanent identifiers, not
authoritative ISINs or Upstox keys. Accordingly, a real sample can demonstrate
price coverage while historical identity coverage remains incomplete.

## Candle Validation

Daily observations are accepted only when they:

- are at or before the manifest cutoff and strictly before the candidate date;
- contain valid positive OHLC relationships;
- contain non-negative volume;
- carry the expected India timezone offset;
- have no duplicate session;
- provide at least the required 121 usable bars.

Candidate-date and future observations are measured and excluded. Missing
sessions are classified only when an authoritative exchange-session calendar is
provided; weekday gaps are not automatically called provider defects because
exchange holidays would be misclassified.

The probe reports observed daily depth. It does not infer daily availability
from Upstox intraday limits.

### Coverage metric semantics

The evidence model keeps each bar stage separate:

- **Raw bars returned:** all provider rows, including malformed rows.
- **Pre-cutoff bars:** parseable rows at or before the required end and strictly
  before the candidate date.
- **Normalized bars:** sorted pre-cutoff rows before integrity rejection and
  session de-duplication.
- **Integrity-valid bars:** unique-session rows with positive valid OHLC,
  non-negative volume, the India timezone, and an allowed exchange session when
  an authoritative calendar is available.
- **Full price coverage:** sufficient integrity-valid depth plus no mandatory
  series defect.

The headline price-coverage rate is full price coverage divided by all observed
candidates. Year coverage uses the same full-coverage numerator. Partial and no
history groups are terminal-status definitions and explicitly exclude invalid
series. `upstox-series-integrity` reports defect attribution and verifies that
the terminal status distribution reconciles to the observed population.

## Adjustment Audit

Project Alpha does not infer adjustment semantics from a visually smooth price
series. Raw versus adjusted status requires an authoritative, effective-dated
split or bonus case with observations on both sides. Volume consistency is
checked separately.

The Upstox response does not itself supply the full corporate-action lineage
required by Alpha's reconstruction policy. In ordinary live sampling the
deterministic result is therefore:

- `ADJUSTMENT_UNDOCUMENTED`;
- `CORPORATE_ACTION_EVIDENCE_REQUIRED`.

An independent authoritative corporate-action source remains necessary.

## Storage and Licensing

Raw Upstox candle responses are held only in memory for validation. Because
local storage and derived-use permission have not been independently accepted
for this trial, persistence retains only non-reversible coverage metrics,
instrument identifiers, requested and returned date ranges, counts, validation
results, and a request-configuration hash.

A deterministic response checksum is calculated in memory for testability but
is not persisted or exported while terms remain uncertain. No raw candle rows
are stored.

## Reliability

Requests are serialized below the documented standard-API limit of 500 requests
per minute. Rate-limit and transient failures honor `Retry-After` where
available and use capped retries. Persistent authentication, expired-token, and
forbidden-endpoint failures stop collection. Evidence is checkpointed after
each candidate and can be resumed only when the manifest, sample, dataset
version, and scope match.

The utility report is a simulation only. It measures price availability,
identity authority, corporate-action authority, reconstruction marginal value,
and observed selection-bias changes separately. It never writes to the
reconstruction dataset and never upgrades candle availability into historical
identity authority.

## Source Acceptance

Authentication success proves only capability access. It does not prove:

- ten-year daily coverage for the difficult historical population;
- historical symbol continuity;
- inactive or renamed security support;
- adjustment semantics;
- corporate-action compatibility;
- storage and derived-use permission.

Upstox remains outside production. It can be considered for secondary price
validation only after sample evidence demonstrates useful price depth. Primary
source acceptance additionally requires full-population coverage, authoritative
point-in-time identity, corporate-action lineage, permitted storage and use,
stable rate limits, and independent reconciliation.
