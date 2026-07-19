# Reconciliation Strategy

**Strategy version:** `HISTORICAL_RECONCILIATION_1.0`  
**Status:** Design only  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Objective

Reconciliation compares Warehouse v1, official NSE, official BSE, depository, index,
and event evidence without erasing source-specific truth. It detects differences,
classifies their cause, and promotes only resolved facts.

## Non-Negotiable Rules

1. Compare at the correct grain: venue + session + security + series.
2. Resolve permanent identity before comparing values.
3. Never join historical rows on today's ticker alone.
4. NSE and BSE prices are separate venue observations. Their natural differences are
   not errors.
5. Official revisions supersede but never delete earlier publications.
6. Legacy evidence can confirm or expose gaps; it cannot overwrite official evidence.
7. Unresolved disagreements remain `CONFLICTED` or `QUARANTINED`.
8. Missing is not zero, and no trade is not the same as a missing file.

## Comparison Populations

| Population | Join | Purpose |
| --- | --- | --- |
| Legacy vs NSE | NSE + session + resolved security + series | Certify or explain Warehouse v1 rows labeled NSE |
| Legacy vs BSE | BSE + session + resolved security + series | Validate any BSE-labeled legacy evidence |
| NSE vs BSE cross-venue | effective-dated ISIN/security lineage + session | Detect identity/action inconsistencies, not enforce equal prices |
| Exchange vs depository | effective-dated ISIN + action/event dates | Confirm identity state and corporate actions |
| Index files vs press releases | index + security + effective date | Confirm constituent additions/removals |
| Calendar vs market files | venue + segment + session | Detect missing reports, special sessions, and calendar errors |

## Required Difference Types

### Price mismatch

Within the same venue and canonical identity, compare unadjusted official fields after
unit normalization:

- open, high, low, close, previous close, last, and VWAP;
- price scale and currency;
- source tick size and rounding convention;
- raw vs adjusted mode.

Official same-file duplicates must match exactly after decimal normalization. Legacy
floating-point values use an explicit tolerance recorded in the reconciliation policy,
never an undocumented epsilon. Any difference near an action date is attributed only
after the action event and adjustment mode are identified.

### Volume mismatch

Compare integer traded quantity at venue/security/series/session grain. Before calling
a mismatch, distinguish:

- shares vs lots;
- traded quantity vs deliverable quantity;
- auction/normal/odd-lot market type;
- equity vs ETF/debt/preference/warrant series;
- corrected file vs original publication.

Volume tolerance is zero after units and scope agree. Aggregation differences receive a
separate reason code.

### Missing day

Classify in this order:

1. official holiday or non-session;
2. special session or muhurat session;
3. source file missing/corrupt;
4. security not listed yet;
5. security suspended/delisted;
6. listed but did not trade;
7. report excludes that instrument/series;
8. identity unresolved;
9. unexplained missing observation.

Only case 9 is an unexplained data gap.

### Symbol or identity mismatch

Detect:

- symbol change with effective date;
- company-name change;
- series migration;
- symbol reuse by a different security;
- ISIN replacement after split/consolidation/scheme;
- merger/demerger predecessor-successor;
- exchange-specific symbol differences;
- invalid future alias used historically.

Resolution requires effective-dated official evidence. String similarity may open a
review case but cannot close one.

### Corporate-action mismatch

Compare action type, announcement/ex/record/payment/effective dates, old/new ISIN,
old/new symbol, face value, ratio, cash consideration, entitlement, and lineage.

Possible outcomes:

- `CONFIRMED_EXCHANGE_DEPOSITORY`;
- `CONFIRMED_EXCHANGE_ISSUER`;
- `DATE_VARIANCE_EXPLAINED`;
- `TERMS_INCOMPLETE`;
- `ACTION_MISSING_FROM_SOURCE`;
- `CONFLICTED_OFFICIAL_TERMS`;
- `COMPLEX_SCHEME_MANUAL_REVIEW`.

An adjusted-price jump is never used to invent an action.

## Reconciliation Pipeline

```text
select immutable source releases
        |
        v
validate rights, checksums, schemas, and session scope
        |
        v
resolve effective-dated identities
        |
        v
normalize units without changing values
        |
        v
build comparable populations
        |
        v
compare fields and source totals
        |
        v
attribute calendar / identity / action / revision causes
        |
        v
CONFIRMED | REVISED | CONFLICTED | QUARANTINED | UNKNOWN
        |
        v
publish reconciliation report and candidate canonical facts
```

## Authority-Specific Resolution Rules

| Conflict | Resolution rule |
| --- | --- |
| NSE official vs Warehouse v1 NSE row | NSE value wins for NSE venue after identity, schema, and revision validation; legacy remains retained as `OBSERVED` |
| BSE official vs Warehouse v1 BSE row | BSE value wins under the same conditions |
| NSE vs BSE close | Keep both official venue values; no winner |
| Earlier vs corrected file from same authority | Later correction applies only from its knowledge time; earlier version remains queryable for prior PIT replay |
| Exchange symbol vs depository issuer name | Exchange controls venue symbol; depository controls ISIN state; preserve both names |
| Exchange ISIN vs depository ISIN conflict | Quarantine identity resolution until effective dates/actions explain it |
| Current master vs dated historical file | Dated historical file controls its effective date; current master is `CURRENT_ONLY` |
| Nifty release vs licensed constituent snapshot | Reconcile effective timestamps; NSE Indices remains authority, conflict stays visible until corrected |
| Public page vs licensed official bulk file | Same authority does not imply identical publication version; retain and reconcile both |

## Tolerances and Units

All tolerances belong to a versioned `ReconciliationPolicy`, including:

- currency and price scale;
- decimal precision;
- legacy float tolerance;
- turnover unit and rounding tolerance;
- volume/lot conversion;
- date/time zone and market cutoff;
- action-date comparison window;
- source-finalization delay.

No tolerance may be hardcoded in a parser or hidden in SQL.

## Output: Reconciliation Case

Every discrepancy stores:

- stable case ID;
- comparison population and policy version;
- entity, field, venue, session, and effective interval;
- left/right source record IDs and values;
- normalized values and units;
- difference magnitude;
- classification and reason code;
- related calendar/identity/action/revision evidence;
- resolution status, confidence, reviewer when required;
- created and resolved timestamps;
- resulting canonical field ID, if any.

## Release Metrics

Report counts and rates by source, year, series, instrument type, and reason:

- expected, compared, matching, revised, conflicted, and quarantined rows;
- missing sessions and security observations;
- OHLC, volume, turnover, identity, and action mismatch rates;
- unexplained mismatch rate;
- unresolved identity and action counts;
- current-only leakage attempts;
- point-in-time publication violations.

Rates must use explicit denominators. A 99.9% match cannot certify a release if the
remaining 0.1% contains unresolved symbol reuse or major corporate actions.

## Promotion Gate

Canonical promotion requires:

- no unresolved checksum/schema failure;
- no future-data leakage;
- no ambiguous identity for promoted rows;
- all mandatory action events resolved for adjusted modes;
- explained/approved residual mismatch budget by field and year;
- retained reconciliation report and input hashes;
- explicit human publication approval.

This design does not set the future numerical mismatch budget. It must be established
from a pilot sample and documented before implementation.
