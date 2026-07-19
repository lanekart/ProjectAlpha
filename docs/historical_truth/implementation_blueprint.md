# Historical Truth Layer Implementation Blueprint

**Blueprint version:** `HISTORICAL_TRUTH_BLUEPRINT_1.0`  
**Current milestone:** Architecture only  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Outcome

This blueprint defines how Alpha can move from a provisional observed-price store to
an authoritative, point-in-time research warehouse without replacing Warehouse v1 or
changing production behavior prematurely.

## Future Component Boundaries

The names below are proposed future boundaries, not modules created by this milestone.

```text
alpha/historical_truth/
  source_registry/       # rights, products, schemas, coverage declarations
  raw_vault/             # immutable bytes, checksums, supersession
  normalization/         # source/era parsers and structural validation
  identity/              # permanent security and identifier history
  corporate_actions/     # raw events, reconciled terms, lineage, factors
  calendars/             # venue/segment sessions and exceptions
  universe/              # listing, tradability, indices, sectors
  reconciliation/        # field comparisons and cases
  confidence/            # field/observation/release assessment
  warehouse/             # canonical facts and immutable release manifests
  publication/           # research-only release gate
```

The Market Truth Engine remains the downstream access boundary. Consumers do not read
the raw vault or canonical database directly.

## Phase 0 — Procurement and Evidence Contract

**Goal:** determine whether sources are legally and technically usable before coding
acquisition.

Deliverables:

- approved source-authorization schema;
- signed/recorded rights for storage, research, retention, backup, corrections,
  derived analytics, and exit;
- data dictionaries and representative samples;
- exact coverage and known-gap statements;
- revision and publication-time policy;
- source RACI and cost approval.

Exit gate: at least one official NSE daily-price source and one viable identity/action
source pass legal and sample review. No downloader is built before this gate.

## Phase 1 — Truth Kernel

**Goal:** implement source-independent evidence primitives.

Build:

- closed truth and resolution enums;
- bitemporal field-truth envelope;
- authorization and raw-object manifests;
- version and release manifests;
- reason-code registry;
- deterministic content hashing;
- schema/version compatibility rules.

Tests:

- immutability;
- unknown/current-only behavior;
- knowledge-time cutoff;
- deterministic IDs/hashes;
- no silent truth-class promotion;
- correction lineage.

Exit gate: truth-kernel conformance suite passes with synthetic fixtures only.

## Phase 2 — Immutable Raw Vault and Session Inventory

**Goal:** retain authorized source evidence before parsing.

Build only after Phase 0 approval:

- content-addressed raw object store;
- atomic manifests and work journal;
- checksum/duplicate/revision handling;
- session/object inventory;
- quarantine and restore drill;
- read-only status/audit CLI.

Exit gate: pilot objects can be restored byte-for-byte and every object links to an
authorization snapshot.

## Phase 3 — NSE Pilot Normalization

**Goal:** prove source/era parsing and reconciliation on a bounded sample.

Pilot datasets:

- UDiFF and pre-UDiFF bhavcopy formats;
- delivery positions;
- CM security/master files;
- public/licensed corporate-action sample;
- official holiday/session evidence.

Include active, renamed, suspended, delisted, split, bonus, merger, and illiquid cases.

Exit gate: schema fingerprints, source totals, identity joins, and known event cases
pass; unexplained mismatches are documented, not waived.

## Phase 4 — Identity and Corporate-Action Foundation

**Goal:** create permanent security history before a bulk price migration.

Build:

- Alpha security IDs;
- exchange code/token, symbol/series, and ISIN intervals;
- listing/suspension/relisting/delisting intervals;
- raw and reconciled action events;
- predecessor/successor lineage graph;
- action-factor policies for simple confirmed events;
- manual-review workflow for complex schemes.

Exit gate: no overlapping aliases, no lineage cycles, no fuzzy-only canonical links,
and a documented unknown share by year.

## Phase 5 — Full Official Backfill and Reconciliation

**Goal:** materialize a complete candidate official venue history.

Activities:

- authorized incremental/backfill acquisition;
- format-era normalization;
- session/security/series coverage audit;
- Warehouse v1 vs official NSE/BSE reconciliation;
- mismatch attribution and quarantine;
- raw, adjusted, total-return, and point-in-time candidate views.

Exit gate: numerical thresholds are defined from the pilot, critical cases pass, and
all remaining unknown/conflict populations are explicit.

## Phase 6 — Point-in-Time Universe Completion

**Goal:** certify what Alpha could trade on each date.

Inputs:

- listing/tradability history;
- instrument type/series policy;
- Nifty 50/100/200/500 historical constituents;
- effective-dated sector history;
- corporate-action lineage;
- security observations and liquidity fields.

Exit gate: no future constituents, no pre-listing/post-delisting members, no current
sector backfill, and unknown dimensions remain visible.

## Phase 7 — Warehouse v2 Candidate and Shadow Validation

**Goal:** compare Warehouse v2 research outputs with Warehouse v1 without replacing it.

Run offline:

- row and coverage reconciliation;
- feature/recommendation parity attribution;
- replay differences by year, regime, action, identity, and universe status;
- statistical and operational impact report;
- clean-room release reproduction.

Exit gate: independent review approves a `PUBLISHED_RESEARCH` release. Warehouse v1
remains the selected baseline unless a separate migration decision is approved.

## Phase 8 — Canonical Alpha Fund Research

**Goal:** run the first survivorship-safe, version-pinned Alpha Fund replay.

Every run pins:

- Warehouse version;
- universe and adjustment versions;
- Feature version;
- Policy version;
- Decision version;
- transaction-cost and market-regime versions;
- market-time and knowledge-time cutoffs.

This is research validation, not capital deployment.

## Phase 9 — Institutional Data Layer

Optional future additions after v2 is stable:

- normalized institutional identity and corporate-action reference;
- BSE expansion where incremental value is measured;
- richer fundamentals and ownership disclosures;
- operational SLAs and vendor failover;
- licensed live/non-display integration under separate controls.

Alternative data remains Warehouse v4 and never silently changes core market truth.

## Conceptual Interfaces

Future implementations should compose small protocols:

```text
SourceAuthorisationRegistry
RawObjectStore
SourceSchemaRegistry
Normalizer
IdentityResolver
CorporateActionReconciler
TradingCalendarService
HistoricalUniverseBuilder
ReconciliationEngine
ConfidenceAssessor
WarehouseReleaseBuilder
ResearchTruthRepository
```

Each interface accepts explicit versions and returns immutable typed results. Provider
plugins remain outside core resolution rules.

## Acceptance Test Families

### Source and raw evidence

- authorization expiry and denied rights fail closed;
- original bytes and checksums are immutable;
- exact, packaging, semantic, and conflicting duplicates classify correctly;
- corrected files preserve knowledge-time lineage;
- restart/resume is idempotent.

### Identity and universe

- IPO inclusion and pre-listing exclusion;
- suspension/relisting/delisting intervals;
- symbol and ISIN changes;
- symbol reuse isolation;
- merger/demerger lineage and cycle prevention;
- point-in-time index and sector membership;
- unknown history does not backfill.

### Market observations

- legacy/UDiFF schema transitions;
- OHLC/volume/turnover domain validation;
- venue separation;
- missing session vs no trade;
- delivery/traded volume separation;
- correction and corporate-action attribution.

### Point-in-time and releases

- no future publication/action/member leakage;
- release hash determinism;
- parent/child correction behavior;
- full clean-room rebuild;
- Warehouse/Feature/Policy/Decision versions in every replay artifact;
- no consumer cutover without explicit selection.

## Required Operational Reports

- source authorization and expiry report;
- expected/received object inventory;
- session and security coverage by year;
- identity and corporate-action coverage;
- index and sector history coverage;
- reconciliation cases and unresolved critical events;
- truth-class/confidence distribution;
- release manifest and reproducibility report;
- Warehouse v1-to-v2 impact report.

## Roadmap

### Historical Truth Engine

Phases 0–4 establish rights, immutable evidence, truth semantics, identity, and action
lineage. This is the first implementation program.

### Canonical Warehouse v2

Phases 5–7 backfill, reconcile, version, and shadow-validate official data. It may be
published for research only after independent approval.

### Canonical Alpha Fund

Phase 8 runs survivorship-safe research on a complete version bundle. Deployment
readiness is assessed from resulting evidence, not assumed from architecture quality.

### Institutional Data Layer

Phase 9 adds licensed normalization and breadth only when measured gaps justify cost
and complexity.

## Deferred by Design

- downloader and credentials;
- source parsers;
- Warehouse v1 migration or replacement;
- replay and recommendation recalculation;
- production routing or policy changes;
- numerical promotion tolerances before a real source pilot;
- unsupported claims about historical coverage.

## Architecture Validation in This Milestone

The repository contains document-level tests that validate required deliverables,
coverage-matrix provenance, closed truth classes, version dimensions, roadmap phases,
and `PRODUCTION_INFLUENCE=false`. They do not test or invoke any data source.
