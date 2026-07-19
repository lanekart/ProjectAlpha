# Canonical Warehouse Architecture

**Target:** Historical Truth Layer feeding a future Warehouse v2  
**Status:** Design only; no ingestion or migration in this milestone  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Architectural Decision

Warehouse v2 must be a bitemporal, evidence-preserving system. It must store both:

- **valid time:** when a market fact applied; and
- **knowledge time:** when Alpha could have known that fact.

A corrected exchange file may improve later research without rewriting what a prior
point-in-time replay was allowed to know. Current values may never fill historical
gaps unless explicitly labeled `CURRENT_ONLY` and excluded from historical use.

## Required Flow

```text
Source and rights registry
          |
          v
Raw Data (immutable original bytes)
          |
          v
Normalization (source-specific, schema-versioned)
          |
          v
Corporate Action Engine (events, terms, lineage, adjustments)
          |
          v
Security Master (permanent identity and effective-dated aliases)
          |
          v
Identity Resolution (venue facts -> permanent security)
          |
          v
Historical Universe (listing, suspension, index, sector, tradability)
          |
          v
Canonical Warehouse (raw and adjusted market facts + provenance)
          |
          v
Research Layer (point-in-time views, replay, features, diagnostics)
```

The sequence is deliberate. A price row cannot safely enter the canonical security
history until the source symbol/series is resolved for that date. Adjusted prices
cannot be generated until action terms and lineage are reconciled. Universe
membership cannot be certified until listing and suspension state are known.

## Logical Zones

### 1. Source and rights registry

Records one immutable authorization snapshot per provider/dataset/effective period:

- provider and official authority;
- dataset and segment;
- acquisition method;
- internal storage, research, retention, backup, derived-use, and redistribution
  rights;
- effective and expiry dates;
- agreement/evidence reference;
- rate and delivery constraints;
- responsible owner and approval.

Unknown permission fails closed. The registry authorizes a source, not its quality.

### 2. Immutable raw vault

Stores exact source bytes without parsing or rewriting. Every object requires:

- `raw_object_id` derived from SHA-256;
- source dataset ID and authority;
- original filename and media type;
- retrieval timestamp and source publication timestamp when known;
- requested/effective session range;
- byte length, checksum, and transport checksum when available;
- authorization snapshot ID;
- schema hint, correction status, and predecessor/superseded object ID;
- quarantine state and reason codes.

Two files for the same date are separate objects. A corrected file supersedes but
does not delete the original.

### 3. Normalized staging

Source adapters map raw records into typed staging schemas while retaining every raw
field. Normalization may standardize dates, decimals, units, enums, and field names;
it may not infer missing values.

Every normalized row retains:

- raw object ID and raw row locator;
- parser and schema versions;
- normalized row checksum;
- source symbol, series, security code, ISIN, and venue exactly as published;
- validation state and reason codes;
- `published_at`, `retrieved_at`, `valid_from`, and `knowledge_from`.

Invalid rows go to quarantine. They never disappear from the audit trail.

### 4. Corporate Action Engine

Maintains raw action announcements separately from reconciled action events.

Core entities:

- action announcement;
- action terms and ratios;
- ex, record, announcement, payment, allotment, and effective dates;
- predecessor and successor securities/ISINs;
- exchange/depository/issuer evidence links;
- reconciliation state;
- adjustment factors and policy version.

Simple split, consolidation, bonus, rights, and dividend events may generate factors
only after required terms pass validation. Merger, demerger, amalgamation, spin-off,
and cash-plus-security arrangements remain unadjusted until lineage and consideration
are complete.

### 5. Security Master

The permanent key is an Alpha `security_id`, never a ticker. The master is a set of
effective-dated facts:

- exchange security code/token;
- symbol and series;
- ISIN and depository status;
- legal issuer/entity identity;
- instrument type and equity eligibility;
- listing, suspension, relisting, and delisting intervals;
- predecessor/successor lineage;
- source and truth class per field.

No row may have overlapping active aliases for the same authority and key type unless
the conflict is explicitly stored as unresolved.

### 6. Identity Resolution

Resolution produces candidates and evidence, not silent guesses. Priority keys are:

1. exchange security ID/code within an effective interval;
2. effective-dated ISIN;
3. official symbol + series + venue within an effective interval;
4. official action/name/symbol event lineage;
5. normalized issuer name only as a review candidate.

Ticker-only matches cannot become `OFFICIAL`. Ambiguous and reused symbols remain
unresolved. Resolution decisions are immutable and versioned.

### 7. Historical Universe

For each session and security, separately records:

- existed/listed status;
- suspension and trading eligibility;
- instrument and series eligibility;
- observed trade/bar state;
- Nifty 50/100/200/500 membership;
- sector/industry assignment;
- corporate-action lineage completeness;
- truth class, confidence, and source for every dimension.

`OBSERVED_TRADE` does not imply `ELIGIBLE_EQUITY`, and a missing bar does not by
itself imply suspension or delisting.

### 8. Canonical Warehouse

Canonical facts are append-only releases over immutable evidence. Minimum fact sets:

- raw venue OHLCV, turnover, trades, VWAP, and deliverables;
- official index levels;
- raw corporate actions;
- effective-dated identity/listing/universe dimensions;
- adjustment factors;
- adjusted and total-return research views;
- trading sessions and special sessions;
- reconciliation exceptions and confidence assessments.

NSE and BSE observations remain distinct by venue. A consolidated research price is
a named derived view, never a replacement for either official venue fact.

### 9. Research Layer

Consumers request an explicit evidence mode and complete version bundle:

- `RAW_OFFICIAL`;
- `POINT_IN_TIME_OFFICIAL`;
- `ADJUSTED_RESEARCH`;
- `TOTAL_RETURN_RESEARCH`;
- `LEGACY_OBSERVED`;
- `MIXED_DIAGNOSTIC` (not promotion eligible).

Every query has `as_of_market_time` and `as_of_knowledge_time`. Research output must
retain Warehouse, feature, policy, and decision versions.

## Proposed Core Tables

| Table | Grain | Important keys |
| --- | --- | --- |
| `source_authorisation` | provider + dataset + entitlement interval | authorization ID |
| `raw_object_manifest` | exact source file/object | content hash |
| `normalized_source_record` | source row | raw object + row locator |
| `security` | permanent instrument | Alpha security ID |
| `security_identifier_history` | security + identifier type + validity interval | authority + value + valid time |
| `listing_status_history` | security + venue + status interval | security + venue + valid time |
| `corporate_action_announcement` | source announcement | authority + source event ID |
| `corporate_action_event` | reconciled economic event | canonical action ID |
| `corporate_action_lineage` | event + predecessor/successor | action + security IDs |
| `trading_session` | venue + segment + session date | venue + date |
| `daily_market_observation` | venue + session + security + series | canonical source fact ID |
| `deliverable_observation` | venue + session + security + series | canonical source fact ID |
| `index_membership_history` | index + security + effective interval | administrator + index + security |
| `sector_membership_history` | taxonomy + security + effective interval | taxonomy version + security |
| `universe_state` | session + security + universe policy | versioned PIT state |
| `reconciliation_case` | field-level comparison case | case ID |
| `field_truth` | entity + field + effective interval | value + truth/provenance envelope |
| `adjustment_factor` | security + event + effective date + policy | factor version |
| `warehouse_release_manifest` | immutable release | Warehouse version |

## Field Truth Envelope

Every canonical field, including null/unknown values, is represented logically as:

```text
entity_key
field_name
value
unit
truth_class
source_record_ids
source_authority
valid_from / valid_to
published_at / knowledge_from
resolution_status
confidence_grade / confidence_components
reconciliation_version
inference_version (nullable)
reason_codes
```

This envelope may be stored columnar, relational, or as companion provenance tables,
but its semantics are mandatory.

## Bitemporal Query Contract

For a query `Q(valid_date=D, knowledge_cutoff=K)`:

1. exclude source records published or first known after `K`;
2. select facts whose valid interval covers `D`;
3. apply only corrections known by `K`;
4. apply corporate actions only according to the requested evidence mode;
5. never use identity, sector, or membership facts whose `knowledge_from > K`;
6. return explicit unknowns and conflicts, not a silent latest-value fallback.

## Promotion Boundaries

Raw, normalized, reconciled, canonical, and published are distinct states.

```text
RECEIVED -> CHECKSUM_VERIFIED -> PARSED -> VALIDATED
         -> RECONCILED -> CANONICAL_CANDIDATE -> PUBLISHED
              \-> QUARANTINED
```

Only a signed release manifest can expose canonical data to research consumers.
Publishing does not affect production until a separate human-approved consumer change
selects that version. This milestone performs neither action.

## Relationship to Existing Alpha Components

- Warehouse v1 remains the `LEGACY_OBSERVED` source.
- The existing point-in-time universe foundation remains a diagnostic consumer and
  should later read an explicit Warehouse v2 release.
- The existing Market Truth Engine remains the consumer boundary; it should eventually
  serve versioned Warehouse v2 evidence rather than direct source internals.
- Existing v4.1 warehouse code is provisional implementation evidence, not an
  automatically certified Warehouse v2 release.
- Recommendation, replay, learning, and production policies are unchanged.

## Non-Goals

This architecture does not provide a downloader, parser, migration, replay, adjusted
price series, source credential, or production routing change.
