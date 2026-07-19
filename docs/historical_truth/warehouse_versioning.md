# Warehouse Versioning

**Contract version:** `HISTORICAL_WAREHOUSE_VERSIONING_1.0`  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Version Families

| Family | Meaning | Current/future status |
| --- | --- | --- |
| Warehouse v1 | Legacy observed OHLCV and existing research store | Preserved, immutable baseline; not authoritative historical truth |
| Warehouse v2 | Official-exchange historical truth with versioned identity/actions/universe | Future target; not built by this milestone |
| Warehouse v3 | Institutional normalized reference/identity/corporate-action layer | Future optional licensed enrichment |
| Warehouse v4 | Alternative data and non-market extensions | Future; isolated from core truth |

Versions are evidence contracts, not marketing labels. A v2 release cannot exist until
its mandatory components and promotion gates pass.

## Immutable Release Identifier

Proposed format:

```text
ALPHA_WH_<major>.<minor>.<patch>+<12-char-content-hash>
```

Example only:

```text
ALPHA_WH_2.0.0+8f31a96c0e21
```

The hash is derived deterministically from the canonical release manifest, which
includes sorted component and raw-object hashes. The example is not an existing
release.

## Semantic Rules

- **Major:** truth contract, key model, or compatibility changes.
- **Minor:** additive dataset/component coverage under the same contract.
- **Patch:** official corrections, parser fixes, or quality remediation that changes
  canonical content without changing the contract.
- **Build hash:** exact immutable contents.

No version is overwritten. A correction creates a child release with a parent link.

## Required Release Manifest

Every release records:

- Warehouse release ID, semantic version, content hash, parent ID, and status;
- schema and truth-classification versions;
- raw manifest hash and every source object hash;
- source-authorization registry snapshot hash;
- provider/dataset coverage, session range, exchanges, and row counts;
- parser/schema versions by source and era;
- security-master and identity-resolution versions;
- corporate-action event and adjustment-policy versions;
- index, sector, listing, suspension, and calendar versions;
- universe policy/version;
- reconciliation and confidence-engine versions;
- truth-class, conflict, quarantine, and unknown distributions;
- point-in-time knowledge cutoff and correction cutoff;
- build timestamp, code commit, environment lock hash, and builder identity;
- quality-gate results and human publication approval;
- `PRODUCTION_INFLUENCE=false` for research releases until separately changed.

## Component Versions

Components advance independently and are pinned by the release:

```text
RAW_MANIFEST_VERSION
NORMALIZATION_SCHEMA_VERSION
SECURITY_MASTER_VERSION
IDENTITY_RESOLUTION_VERSION
CORPORATE_ACTION_VERSION
ADJUSTMENT_POLICY_VERSION
TRADING_CALENDAR_VERSION
INDEX_MEMBERSHIP_VERSION
SECTOR_HISTORY_VERSION
UNIVERSE_VERSION
RECONCILIATION_VERSION
CONFIDENCE_MODEL_VERSION
```

A component alias such as `latest` is prohibited in a replay manifest.

## Replay Provenance Bundle

Every replay, recommendation snapshot, experiment, and performance result must record:

```text
Warehouse Version
Feature Version
Policy Version
Decision Version
```

It must additionally retain, where relevant:

- universe version;
- adjustment mode/policy;
- transaction-cost policy;
- market-regime classifier version;
- code commit and run ID;
- as-of market and knowledge cutoffs.

Two results are comparable only when their metric definitions and relevant version
dimensions are equal or an explicit compatibility analysis says otherwise.

## Release States

```text
DRAFT
  -> MATERIALIZED
  -> VALIDATED
  -> RECONCILED
  -> CANDIDATE
  -> PUBLISHED_RESEARCH
  -> DEPRECATED (still readable)

Any state -> REJECTED (still retained)
```

`PUBLISHED_RESEARCH` does not mean production-selected. Production selection requires
a separate human-approved policy/configuration change outside this architecture task.

## Corrections and Knowledge Time

Suppose an exchange publishes file A on T and correction B on T+2:

- the raw vault retains A and B;
- the child release records B superseding A;
- a point-in-time query with knowledge cutoff T+1 sees A;
- a corrected historical query after T+2 may see B;
- the release lineage explains the difference.

No correction rewrites the historical evidence available to an earlier decision.

## Compatibility Policy

| Change | Compatibility |
| --- | --- |
| Add an optional field | Minor-compatible |
| Add source coverage without changing existing facts | Minor-compatible, new release required |
| Official correction changes values | Patch, content-breaking for exact results |
| Parser bug changes normalized facts | Patch with mandatory impact report |
| Permanent key or truth semantics change | Major |
| Adjustment policy changes | New component version; exact replay incompatible |
| Confidence model changes only | New assessment version; raw facts unchanged |

## Warehouse v1 Preservation

Warehouse v1 remains addressable by a frozen manifest containing its observed range,
schema, row counts, database hash, and known limitations. During future migration:

- v1 rows are reconciled, not overwritten;
- matched v1 values retain `OBSERVED` provenance;
- official v2 facts are new records;
- unexplained v1-only rows remain visible as exceptions;
- consumer cutover is opt-in and version-pinned.

## Retention

Raw objects, manifests, reconciliation cases, published releases, and any release used
by a replay/recommendation are non-deletable under normal operation. If a legal
agreement requires deletion, Alpha records a tombstone manifest and impact report;
it never silently reuses the retired version ID.
