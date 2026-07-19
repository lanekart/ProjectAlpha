# Historical Truth Confidence Engine

**Model version:** `HISTORICAL_CONFIDENCE_1.0`  
**Status:** Design only  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Purpose

Confidence answers: “How safe is this field or observation for its declared use?” It
does not convert inferred data into official truth, resolve conflicts, or authorize a
source.

The engine returns:

- component scores and gates;
- a numeric diagnostic score from 0 to 100 when evidence exists;
- `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`;
- caps, vetoes, and reason codes;
- the confidence model version.

## Assessment Grain

Confidence is computed at three grains:

1. **field confidence**: one value and effective interval;
2. **observation confidence**: required fields for one market row;
3. **release confidence**: coverage-weighted component summary plus hard gates.

A high-confidence price does not imply high-confidence identity or universe
membership. Release confidence is never the arithmetic average of unrelated facts.

## Components

| Component | Weight | Question |
| --- | ---: | --- |
| Source authority | 30 | Is the provider authoritative for this field and is use authorized? |
| Reconciliation | 20 | Do independent admissible records agree, or is a revision resolved? |
| Completeness | 15 | Are required sessions/fields present with documented gaps? |
| Identity certainty | 15 | Is the row tied to a permanent security for the effective date? |
| Corporate-action safety | 10 | Are relevant action terms/lineage complete for the requested mode? |
| Point-in-time safety | 10 | Are publication, knowledge, and valid times known and respected? |
| **Total** | **100** | Diagnostic score before caps/vetoes |

Each component stores its measured basis and reason codes. Missing evidence scores
zero for that component; it is not assigned a neutral midpoint.

## Grade Bands

| Grade | Score band | Minimum interpretation |
| --- | --- | --- |
| `HIGH` | 85–100 | Official/authorized evidence, secure identity and timing, no unresolved critical conflict |
| `MEDIUM` | 65–84 | Useful evidence with bounded and disclosed gaps |
| `LOW` | 1–64 | Material limitations; diagnostic use only unless a consumer explicitly permits it |
| `UNKNOWN` | No admissible evidence | Confidence cannot be measured |

Bands apply only after truth-class caps and hard vetoes.

## Truth-Class Caps

| Truth class / status | Maximum grade | Reason |
| --- | --- | --- |
| `OFFICIAL + CONFIRMED` | `HIGH` | Authority plus reconciliation can support certification |
| `OFFICIAL + UNCONTESTED` | `HIGH` | High possible if completeness, identity, actions, and timing pass |
| `OFFICIAL + CONFLICTED` | `LOW` | Authority cannot hide unresolved disagreement |
| `OBSERVED` | `MEDIUM` | Direct observation is useful but not official truth |
| Warehouse v1 `OBSERVED` without permanent identity/action lineage | `LOW` | Known structural limitations apply |
| `INFERRED` | `MEDIUM` | Reproducible derivation remains non-official |
| `CURRENT_ONLY` used at its current effective snapshot | `MEDIUM` | Valid current reference but no historical depth |
| `CURRENT_ONLY` requested for an earlier date | `UNKNOWN` | Historical value is unsupported |
| `UNKNOWN` | `UNKNOWN` | No evidence exists |
| `QUARANTINED` | `UNKNOWN` for canonical use | Evidence failed a mandatory gate |

## Hard Vetoes

Any veto prevents `HIGH`, regardless of total score:

- source storage/research/retention rights are unconfirmed;
- raw checksum fails or original bytes are unavailable;
- permanent identity is unresolved or ambiguous;
- a required field has an unresolved official conflict;
- a future publication or current-only value leaks into a point-in-time query;
- split/bonus/merger/demerger terms required for the selected adjustment mode are
  incomplete;
- session/calendar state is inconsistent with the source observation and unresolved;
- source file is quarantined or parser schema is unknown;
- release manifest is unsigned/unpublished.

## Component Rules

### Source authority (0–30)

- 30: responsible official authority and recorded authorization permits intended use;
- 24: licensed vendor supplies traceable official exchange data and rights are clear;
- 15: direct observed local evidence with stable provenance;
- 5: secondary source suitable only for discovery;
- 0: source unknown, rights unknown, or provenance missing.

### Reconciliation (0–20)

- 20: independent admissible evidence agrees or official correction is resolved;
- 14: one official source passes internal totals and continuity checks;
- 8: observed evidence agrees with official source but independence is limited;
- 0: no comparison where required, conflict, or unexplained mismatch.

Two copies of the same upstream feed are not independent evidence.

### Completeness (0–15)

Computed from explicit expected population at the correct grain. It considers required
fields, expected sessions, source-declared gaps, and report totals. Late/current
partitions are evaluated under a separately documented finalization window.

### Identity certainty (0–15)

- 15: permanent security plus effective-dated exchange ID and ISIN agree;
- 10: official exchange ID resolves but cross-venue/depository confirmation is absent;
- 5: symbol + series + venue resolves uniquely within a documented interval;
- 0: ticker-only, ambiguous, reused, or unresolved.

### Corporate-action safety (0–10)

- 10: no relevant event or all required events/terms are confirmed;
- 6: raw mode is safe but adjusted continuity has incomplete events;
- 0: selected view requires unresolved action terms or lineage.

### Point-in-time safety (0–10)

- 10: publication and knowledge times are exact and cutoff-safe;
- 6: official daily publication window is documented but exact timestamp is absent;
- 2: retrieval date only, with bounded approximation disclosed;
- 0: future/current data may have leaked or timing cannot be bounded.

## Observation Grade Rules

Each observation declares a required-field profile. For `RAW_OFFICIAL_DAILY_EQUITY`:

- venue, session, security ID, symbol-as-traded, series/instrument type;
- open, high, low, close, and volume;
- raw object, source row, publication/knowledge timestamps;
- truth class and reconciliation status.

Optional turnover, trades, VWAP, and deliverables do not make OHLCV missing, but their
own fields remain unknown and reduce completeness for consumers requiring them.

## Release Confidence

A Warehouse release reports:

- row-weighted and security/session-weighted grade distributions;
- unknown and conflicted shares by field family;
- identity, corporate-action, index, sector, and calendar coverage separately;
- all veto counts;
- worst mandatory component;
- confidence-model version.

Release grade is the lowest grade among mandatory components for the declared release
profile. This prevents millions of valid price rows from masking zero historical index
or sector coverage.

## Current Baseline Assessment

| Component | Current status | Grade |
| --- | --- | --- |
| Legacy observed OHLCV | 4,898,586 locally observed rows, incomplete original authority chain | `LOW` |
| Permanent identity | Provisional ticker-keyed identities only | `LOW` |
| Historical Nifty membership | No authoritative history ingested | `UNKNOWN` |
| Historical sector | No effective-dated authority ingested | `UNKNOWN` |
| Corporate-action completeness | Not established | `UNKNOWN` |
| Official listing/suspension history | Not established | `UNKNOWN` |
| Point-in-time observed-universe bounds | 2,466 sessions with no detected future-constituent leak | `LOW` overall because missing dimensions remain material |

The current overall confidence remains `LOW`. This is not a criticism of observed
price volume; it is the correct consequence of unresolved historical identity and
universe truth.

## Determinism and Audit

The engine must persist input hashes, component values, caps, vetoes, final grade,
model version, and calculation timestamp. Recomputing the same release under the same
model must produce the same result. A confidence-model change creates a new assessment;
it never rewrites the old one.
