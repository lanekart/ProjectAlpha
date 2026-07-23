# HTR-010B1F — Official Identity and Series Bridge Certification

## Purpose

HTR-010B1F certifies or explicitly fail-closes the remaining identity and series bridges after HTR-010B1E2 repaired final admission-state propagation.

The governed population is fixed at:

- 23 uncertified cross-ISIN bridge cases.
- 1 uncertified cross-series bridge case: KOTYARK `EQ → BE`.
- 20 unique evidence dossiers, including four dossiers shared by two immutable factor cases.

The milestone does not modify corporate-action factors, run a benchmark replay, integrate adjusted replay, or change production policy.

## Contracts

- Certification: `HTR-010B1F-v1.0.0`
- Completion bundle: `HTR-010B1F-COMPLETE-v1.0.0`
- Evidence manifest: `HTR-010B1F-EVIDENCE-v1.0.0`
- Unique dossiers: `HTR-010B1F-DOSSIER-v1.0.0`
- Discovery registry: `HTR-010B1F-DISCOVERY-v1.0.0`
- Discovery population: `HTR-010B1F-DISCOVERY-POPULATION-v1.0.0`
- Governed download: `HTR-010B1F-DOWNLOAD-v1.0.0`
- Acquisition: `HTR-010B1F-ACQUISITION-v1.0.0`
- Case materialization: `HTR-010B1F-MATERIALIZE-v1.0.0`
- Upstream cases: `HTR-010B1D2-v1.0.0`

## Decision states

Every bridge case ends in exactly one state:

- `CERTIFIED_CONTINUOUS_IDENTITY`
- `CERTIFIED_NONCONTINUOUS_IDENTITY`
- `INSUFFICIENT_OFFICIAL_EVIDENCE`
- `CONFLICTING_OFFICIAL_EVIDENCE`

No case may be silently assumed continuous.

## Completion workflow

The single `official-bridge-complete` command runs:

1. 24-case evidence manifest creation.
2. Collapse into 20 document-acquisition dossiers without merging certification decisions.
3. Blank governed discovery registry creation.
4. Reviewed source-finding population with fail-closed validation.
5. Optional allowlisted official-document download.
6. Raw-byte preservation and SHA-256 recording.
7. Acquisition verification against dossier, source, date, path and hash.
8. Dossier evidence expansion back into all 24 immutable case IDs.
9. Independent case-level continuity certification.
10. Executive readiness and blocker reconciliation.

Discovery, download and certification remain separate trust boundaries. A search result or URL is never evidence. Only downloaded and byte-verified official documents can become admissible evidence.

## Continuity dimensions

B1F treats these as separate claims:

- identity continuity;
- price-series continuity;
- tradability continuity;
- factor-basis compatibility;
- adjusted-replay eligibility.

Cross-series adjusted-replay eligibility requires explicit tradability continuity. Even a certified identity may remain segmented or replay-ineligible.

## Completion CLI

No-download governed baseline:

```bash
poetry run python -m alpha historical-truth \
  official-bridge-complete \
  --htr010b1d2-output \
    artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --no-download-documents \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_completion_2026
```

Reviewed findings and official downloads:

```bash
poetry run python -m alpha historical-truth \
  official-bridge-complete \
  --htr010b1d2-output \
    artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --reviewed-findings \
    artifacts/htr010b1f_reviewed_official_findings.json \
  --download-documents \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_completion_2026
```

The command writes stage-specific artifacts under numbered subdirectories plus:

- `htr010b1f_completion_report.json`
- `htr010b1f_completion_report.md`

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
- Adjusted replay integration: disabled
- Production influence: false

A no-evidence or partially evidenced run may validly conclude `NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION`. B1F certifies evidence; it does not activate replay.
