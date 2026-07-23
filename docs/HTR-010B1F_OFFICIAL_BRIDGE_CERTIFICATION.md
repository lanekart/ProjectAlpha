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
- Upstream case contract: `HTR-010B1D2-v1.0.0`

## Decision states

Every bridge case must receive exactly one decision:

- `CERTIFIED_CONTINUOUS_IDENTITY`
- `CERTIFIED_NONCONTINUOUS_IDENTITY`
- `INSUFFICIENT_OFFICIAL_EVIDENCE`
- `CONFLICTING_OFFICIAL_EVIDENCE`

There is no implicit continuity state.

## Official evidence hierarchy

The engine accepts only evidence classified as one of:

1. NSE security master.
2. NSE symbol-change notice.
3. NSE corporate-action notice.
4. NSE scheme-of-arrangement notice.
5. NSE listing notice.
6. NSE suspension or relisting notice.
7. NSE delisting notice.
8. NSE issuer filing.
9. BSE official notice.
10. Depository official record.
11. SEBI official order.

Every accepted evidence row must include:

- official source class;
- official document ID;
- official document date;
- effective date;
- SHA-256 provenance;
- predecessor and successor identity fields;
- explicit continuity conclusions.

Price similarity, ticker similarity, company-name similarity, ATR-gap restoration, and factor performance are not certification evidence.

## Evidence record schema

Each evidence row is expected to contain:

```text
bridge_case_id
evidence_id
source_class
document_id
document_date
effective_date
source_url
source_sha256
pre_isin
post_isin
pre_symbol
post_symbol
pre_series
post_series
identity_continuity_certified
price_series_continuity_certified
tradability_continuity_certified
official_evidence_excerpt
review_notes
production_influence
```

## Cross-ISIN rules

A cross-ISIN bridge is certified only when official effective-dated evidence explicitly links the predecessor and successor identities.

Certification of identity continuity does not by itself prove price-series continuity. Adjusted-replay certification additionally requires official price-series continuity and a confirmed factor basis.

## Cross-series rules

The KOTYARK `EQ → BE` case separates four questions:

1. Is the economic identity continuous?
2. Is the price series comparable across the boundary?
3. Is tradability continuous across the series transition?
4. Is adjusted replay eligible across the boundary?

Cross-series adjusted-replay eligibility requires all three continuity dimensions. An identity-continuous but tradability-discontinuous transition remains replay-ineligible and should be segmented in the later reconciliation milestone.

## CLI

Build the fixed 24-case acquisition manifest:

```bash
poetry run python -m alpha historical-truth \
  official-bridge-evidence-manifest \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --output artifacts/htr010b1f_official_bridge_evidence_manifest_2026
```

Run certification with no evidence to verify deterministic fail-closed behavior:

```bash
poetry run python -m alpha historical-truth \
  official-bridge-certify \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_official_bridge_certification_no_evidence_2026
```

Run certification after governed official evidence is populated:

```bash
poetry run python -m alpha historical-truth \
  official-bridge-certify \
  --htr010b1d2-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --official-evidence artifacts/htr010b1f_official_bridge_evidence_manifest_2026/htr010b1f_official_evidence.json \
  --start 2026-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b1f_official_bridge_certification_2026
```

## Acceptance invariants

```text
contract_version = HTR-010B1F-v1.0.0
input_bridge_case_count = 24
cross_isin_case_count = 23
cross_series_case_count = 1
unclassified_bridge_case_count = 0
silent_identity_assumption_count = 0
implementation_defect_count = 0
benchmark_replay_count = 0
production_influence = false
```

Every case must remain explicit even when official evidence is unavailable.

## Non-goals

- No factor-formula changes.
- No market-derived factor autocorrection.
- No bridge certification from price behavior.
- No benchmark replay.
- No adjusted replay integration.
- No approval-policy change.
- No production-policy change.

## Expected next milestone

`HTR-010B1G — Post-Certification Admission and Readiness Reconciliation`

B1G will consume B1F decisions, rebuild the interval and quarantine population, and determine whether bridge blockers can be removed. B1F itself does not alter replay admission.

`PRODUCTION_INFLUENCE=false`
