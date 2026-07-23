# HTR-010B1F Official Evidence Certification Bundle

## Purpose

This bundle performs the substantive official-evidence work for the fixed B1F population of 20 dossiers and 24 independent bridge cases.

It does not infer continuity from symbols, prices, URL discovery, or search-engine results. A dossier is positively certified only when downloaded official bytes collectively prove:

1. the pre-event ISIN;
2. the effective-dated corporate action or series transition; and
3. the post-event ISIN.

## Contract

`HTR-010B1F-EVIDENCE-CERTIFICATION-v1.0.0`

## Command

```bash
poetry run python -m alpha historical-truth \
  official-bridge-evidence-certify-all \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_official_evidence_certification_bundle_2026
```

The default source catalog is:

```text
alpha/historical_truth/official_bridge_evidence_source_catalog.json
```

## Pipeline

1. Rebuild the immutable 24-case B1D2 manifest.
2. Collapse cases into 20 unique evidence dossiers.
3. Match dossiers to the reviewed source catalog by effective date and ISIN pair.
4. Create three governed document roles per complete dossier:
   - `PRE_IDENTITY`
   - `CORPORATE_ACTION`
   - `POST_IDENTITY`
5. Download only allowlisted official HTTPS sources.
6. Preserve raw bytes and SHA-256 provenance.
7. Semantically verify the downloaded bytes against the governed dossier.
8. Emit continuity flags only for complete packages.
9. Re-run acquisition, materialization and independent case certification.
10. Export one final evidence-certification report.

## Current catalog state

The catalog contains all 20 governed dossiers.

- 19 dossiers have all three source roles populated.
- MCX remains explicitly incomplete because an official static pre-event source containing `INE745G01035` has not yet been identified in the approved source set.
- No secondary-source URL is used as a substitute.

The catalog is source discovery, not certification. A populated package can still fail semantic review when the downloaded page does not contain the required governed tokens.

## Semantic review

Cross-ISIN packages require downloaded official bytes proving:

- old ISIN in the pre-identity document;
- symbol, effective date and corporate-action terminology in the action document;
- new ISIN in the post-identity document.

A missing token, failed download or absent document leaves the dossier in:

```text
INSUFFICIENT_SEMANTIC_PACKAGE_EVIDENCE
```

Identity certification remains separate from:

- price-series continuity;
- tradability continuity;
- factor compatibility; and
- adjusted-replay eligibility.

The package reviewer therefore does not automatically certify price-series or replay continuity.

## Guardrails

- No benchmark replay
- No adjusted replay integration
- No factor-formula changes
- No production-policy changes
- No price-similarity certification
- `PRODUCTION_INFLUENCE=false`
