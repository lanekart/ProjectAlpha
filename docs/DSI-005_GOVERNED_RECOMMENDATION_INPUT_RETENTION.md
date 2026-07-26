# DSI-005 Governed Recommendation Input Retention

## Purpose

DSI-005 closes the evidence-retention defect certified by DSI-004. It separates
two questions:

1. Which historical recommendation inputs can be recovered without inference?
2. How will Alpha retain every required input and output for future governed
   recommendations?

The subsystem is research infrastructure. It does not change recommendation,
approval, allocation, execution, learning, or live behavior.

`PRODUCTION_INFLUENCE=false`.

## Accepted Source Boundary

The primary command requires the signed DSI-004 certificate. Validation checks:

- DSI-004 contract and readiness;
- certificate report hash;
- all support-artifact hashes;
- implementation source hashes;
- path safety;
- research-only governance flags.

DSI-005 never modifies DSI-004 or earlier artifacts.

## Retrospective Materialisation

DSI-005 decomposes every excluded DSI-004 candidate into field-level deficits.
It records the required historical producer, expected primitive, historical
version, semantic importance, and derivability state.

A value is admissible only when it is:

- retained exactly;
- exactly derivable from immutable point-in-time primitives; or
- exactly derivable through a signed versioned mapping.

Current defaults, future information, present-day classifications, summary-row
lookalikes, and unknown historical policies are prohibited.

The certified population has one deficit signature across 1,330 excluded
candidates. Each lacks 15 required input groups. The signed evidence does not
retain candidate-specific primitive packages or enough historical algorithm,
policy, and serializer lineage to complete them safely. DSI-005 therefore
admits no additional historical candidate.

BEL remains the sole replayable candidate through its retained DSI-002A frozen
snapshot and DSI-004 parity evidence.

## Prospective Recorder

`IntelligenceApplicationService` exposes an optional
`GovernedRecommendationSnapshotRecorder` seam.

The default is:

```text
governed_recommendation_snapshot_capture_enabled=false
```

Enabling capture without an injected recorder fails closed. With capture
disabled, the service follows the original execution path and performs no
snapshot writes.

The canonical recorder captures:

- complete `IntelligenceInputSet`;
- canonical `RecommendationReport` payloads;
- recommendation fingerprints;
- economic-candidate and candidate-arm identities;
- complete-stack allocation and institutional state;
- recorded plan identities;
- outcome-link identities;
- recommendation, serializer, fingerprint, and application source hashes;
- a package manifest and package SHA-256.

Files are created exclusively. An identical repeated capture is idempotent. A
different package for the same identity is rejected and never overwrites the
existing package.

Snapshot packages reject credential-like fields such as access tokens, API
keys, authorization codes, client secrets, passwords, and refresh tokens.

## Round-Trip Replay

The public rehydrator:

1. validates package and source-independent hashes;
2. reconstructs typed `IntelligenceInputSet` values;
3. discards the original application objects;
4. reruns the canonical recommendation application;
5. verifies input, recommendation, fingerprint, allocation, and plan parity.

Canonical normalization explicitly handles dataclasses, dates, decimals, enums,
tuples, immutable mappings, and nullable fields.

Tamper validation covers:

- input snapshot;
- recommendation fingerprint;
- policy hash;
- complete-stack trace;
- plan identity;
- source manifest;
- outcome links;
- secret insertion.

## CLI

Run DSI-005:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-recommendation-snapshot-retention \
  --dsi004-certificate <PATH> \
  --output <PATH>
```

Validate the DSI-005 package:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-recommendation-snapshot-retention-verify \
  --certificate <PATH> \
  --require-ready
```

Validate and replay one prospective snapshot:

```bash
poetry run python -m alpha benchmark \
  verify-recommendation-snapshot \
  --snapshot-package <PATH> \
  --replay
```

## Artifacts

DSI-005 emits field-level deficit and derivability ledgers, historical snapshot
JSONL, field provenance, parity and point-in-time evidence, renewed population
and DSI-002 results, prospective capture and round-trip evidence, tamper probes,
reconciliation, an executive report, and a signed certificate.

Artifacts are deterministic, schema-stable, hash-bound, free of machine-local
paths, and explicit about unknown evidence.

## Readiness Interpretation

Retrospective readiness and prospective readiness are independent.

- Retrospective: `NO_SAFE_RETROSPECTIVE_EXPANSION`
- Prospective: `PROSPECTIVE_CAPTURE_READY`
- Final: `READY_FOR_GOVERNED_RECOMMENDATION_SNAPSHOT_RETENTION`

The final state means the retention mechanism is technically ready for explicit
governed research use. It does not enable capture by default, authorize
production writes, make an economic claim, or change any policy.

## Known Limitations

- 1,330 historical candidates remain unrecoverable under current evidence.
- DSI-004 transfer remains empirically limited to BEL.
- No new comparable outcome or gate-value evidence is created.
- Prospective accumulation begins only after a human explicitly configures a
  governed recorder.
- Outcome linkage is append-only identity infrastructure; DSI-005 does not
  create or backfill outcomes.

## Governance

All DSI-005 policy and influence flags are false:

- no threshold or gate-order changes;
- no historical-value inference;
- no current-default backfill;
- no synthetic recommendations, candidates, approvals, trades, or outcomes;
- no production snapshot writes;
- no default snapshot capture;
- no recommendation, portfolio, execution, learning, live, or production
  influence.

`PRODUCTION_INFLUENCE=false`.
