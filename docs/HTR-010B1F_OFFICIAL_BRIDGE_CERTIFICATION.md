# HTR-010B1F — Official Identity and Series Bridge Certification

## Purpose

HTR-010B1F certifies or explicitly fail-closes the remaining identity and series bridges after HTR-010B1E2 repaired final admission-state propagation.

The governed population is fixed at:

- 23 uncertified cross-ISIN bridge cases.
- 1 uncertified cross-series bridge case: KOTYARK `EQ → BE`.

The milestone does not modify corporate-action factors, run a benchmark replay, integrate adjusted replay, or change production policy.

## Contracts

- Certification contract: `HTR-010B1F-v1.0.0`
- Evidence-manifest contract: `HTR-010B1F-EVIDENCE-v1.0.0`
- Unique-dossier contract: `HTR-010B1F-DOSSIER-v1.0.0`
- Acquisition contract: `HTR-010B1F-ACQUISITION-v1.0.0`
- Upstream case contract: `HTR-010B1D2-v1.0.0`

## Decision states

Every bridge case must end in exactly one state:

- `CERTIFIED_CONTINUOUS_IDENTITY`
- `CERTIFIED_NONCONTINUOUS_IDENTITY`
- `INSUFFICIENT_OFFICIAL_EVIDENCE`
- `CONFLICTING_OFFICIAL_EVIDENCE`

No case may be silently assumed continuous.

## Evidence flow

The evidence lifecycle is deliberately split into four stages:

1. The 24 immutable bridge cases are exported as evidence requests.
2. Duplicate document searches are collapsed into 20 unique dossiers while retaining all case IDs.
3. Official URLs are staged as discoveries, but URL discovery alone is never admissible evidence.
4. Downloaded document bytes are hashed and verified before an admissible evidence file is produced.

Only records in `htr010b1f_admissible_official_evidence.json` may be supplied to the certification engine.

A discovery remains fail-closed when:

- the source class is not approved;
- the dossier ID is unknown;
- the URL is not HTTPS;
- document ID or document date is missing;
- the downloaded file is absent;
- or the expected and actual SHA-256 hashes disagree.

## Continuity dimensions

B1F treats the following as separate claims:

- identity continuity;
- price-series continuity;
- tradability continuity;
- factor-basis compatibility;
- adjusted-replay eligibility.

Cross-series adjusted replay requires all of them, including explicit tradability continuity.

## CLI workflow

```bash
poetry run python -m alpha historical-truth \
  official-bridge-evidence-manifest \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --output artifacts/htr010b1f_official_bridge_evidence_manifest_2026
```

```bash
poetry run python -m alpha historical-truth \
  official-bridge-evidence-dossiers \
  --evidence-manifest-output artifacts/htr010b1f_official_bridge_evidence_manifest_2026 \
  --output artifacts/htr010b1f_official_bridge_evidence_dossiers_2026
```

```bash
poetry run python -m alpha historical-truth \
  official-bridge-evidence-acquire \
  --dossiers artifacts/htr010b1f_official_bridge_evidence_dossiers_2026/htr010b1f_evidence_dossiers.json \
  --discoveries artifacts/htr010b1f_official_bridge_discoveries_2026.json \
  --downloaded-documents-root alpha_data/evidence/htr010b1f \
  --output artifacts/htr010b1f_official_bridge_evidence_acquisition_2026
```

```bash
poetry run python -m alpha historical-truth \
  official-bridge-certify \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --official-evidence artifacts/htr010b1f_official_bridge_evidence_acquisition_2026/htr010b1f_admissible_official_evidence.json \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_official_bridge_certification_2026
```

## Acceptance invariants

- Input bridge cases: 24
- Cross-ISIN cases: 23
- Cross-series cases: 1
- Unique evidence dossiers: 20
- Multi-case dossiers: 4
- Unclassified cases: 0
- Silent identity assumptions: 0
- Implementation defects: 0
- Benchmark replays: 0
- Production influence: false

Readiness may remain `NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION` after B1F. Bridge certification is not replay integration.
