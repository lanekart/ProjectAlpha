# HTR-010B8 Governed Point-in-Time Adaptive Evidence Lineage, Fingerprint Parity, and Publication-Path Certification

## Purpose

HTR-010B8 explains why the institutional candidate receives unavailable adaptive
sample count, posterior, expectancy, and evidence strength even though HTR-010B7
reconstructed governed forward outcomes.

The milestone is diagnostic and policy neutral. It does not publish adaptive
metadata into the canonical recommendation path, mutate the production
recommendation ledger, change fingerprint matching, change the 60-sample
institutional threshold, or influence recommendation, approval, portfolio,
execution, learning, active replay, or production behavior.

## Required handoff

The command requires a signed HTR-010B7 certificate in
`READY_FOR_GOVERNED_SETUP_MATCHED_EVIDENCE_RESEARCH` state. B8 validates B7 with
`require_ready=True` and verifies every B7 supporting artifact before reading:

- `htr010b7_candidate_evidence_sufficiency.csv`;
- `htr010b7_outcome_coverage_ledger.csv`.

B8 also binds the current source files that define:

- the canonical intelligence orchestrator;
- recommendation construction and metadata publication;
- institutional candidate consumption;
- adaptive-learning statistics and calibration;
- recommendation-to-ledger recording;
- recommendation and ledger fingerprint construction.

## Point-in-time shadow evidence

For each B7 candidate, B8 builds a shadow `SetupFingerprint` from the dimensions
that B7 exported. Dimensions not exported by B7 remain explicitly `UNKNOWN`; they
are not inferred.

Potential matching outcomes are isolated by:

- price arm;
- exact shadow fingerprint;
- completed outcome status;
- inferred completion date strictly before the candidate date.

B7 did not export the exact exit date. For completed outcomes, B8 derives an
auditable completion-date proxy as:

```text
candidate decision date + B7 holding_period_days
```

The proxy is used only to fail closed on same-date and future evidence. Rows with
missing holding period remain ineligible. The eligibility ledger records every
decision, the inferred completion date, and the exclusion reason.

RAW and ADJUSTED rows remain separate research arms. They are paired views and are
never added together as independent economic observations.

## Existing adaptive engine

B8 does not create a new estimator. Eligible shadow outcomes are supplied to the
existing `AdaptiveLearningEngine`, which produces:

- completed sample count;
- win and loss counts;
- expectancy;
- Bayesian prior and posterior win probability;
- confidence bounds;
- evidence strength;
- adjusted confidence.

No result is written back to a recommendation, institutional candidate, or
production ledger.

## Publication contract

The institutional adapter consumes five metadata keys:

```text
adaptive_adjusted_confidence
adaptive_evidence_strength
adaptive_posterior_probability
adaptive_expectancy
adaptive_sample_count
```

B8 inspects the current source contract and records whether:

1. the institutional consumer expects each key;
2. `RecommendationEngine._build_one()` publishes it;
3. `IntelligenceApplicationService.run()` invokes adaptive assessment.

A missing field is ready-research evidence only when the gap is fully attributable
to the current source contract. Unexplained publication loss blocks readiness.

## Fingerprint parity

Adaptive matching uses a 13-dimension `SetupFingerprint`. B8 distinguishes:

- the coarse dimensions exported by B7;
- the recommendation fingerprint contract;
- the ledger-entry fingerprint contract;
- the adaptive lookup fingerprint.

The current recorder probe demonstrates the behavior of the actual fingerprint
functions. It verifies whether omission of `candle_pattern` and
`retracement_state` from `key_indicator_snapshot` changes the ledger fingerprint.
A second complete-snapshot probe proves whether exact parity is reachable without
changing matching policy.

A detected, fully explained recorder omission may be certified for governed
research. An unexplained mismatch blocks readiness.

## Evidence-source separation

B8 compares but never merges:

1. adaptive learning evidence from completed recommendation outcomes;
2. strategy-regime historical edge;
3. trade-strategy statistical edge from local bar matching;
4. B7 governed forward-outcome evidence.

The evidence-source artifact records the matching definition, sample unit, time
boundary, primary consumer, and non-equivalence of each source. Statistical edge
or strategy-regime sample size may not be substituted for
`adaptive_sample_count`.

## Deterministic probes

The milestone exercises:

- strictly prior completed outcome inclusion;
- same-date completion exclusion;
- future completion exclusion;
- pending outcome exclusion;
- one-dimension fingerprint mismatch exclusion;
- opposite price-arm exclusion;
- zero-sample fail-closed behavior;
- one-sample adaptive assessment;
- current recorder fingerprint-gap attribution;
- complete snapshot parity;
- adaptive metadata consumer round trip;
- malformed adaptive numeric metadata fail-closed behavior;
- deterministic repeatability.

## Readiness states

- `READY_FOR_GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH`
- `BLOCKED_BY_EMPTY_POINT_IN_TIME_ADAPTIVE_POPULATION`
- `BLOCKED_BY_FINGERPRINT_CONTRACT_MISMATCH`
- `BLOCKED_BY_UNEXPLAINED_ADAPTIVE_EVIDENCE_PUBLICATION_GAP`
- `BLOCKED_BY_POINT_IN_TIME_EVIDENCE_LEAKAGE`
- `BLOCKED_BY_ADAPTIVE_EVIDENCE_IMPLEMENTATION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCE`

A fully attributed current publication or recorder gap may be certified in the
ready research state. Readiness means only that the lineage and root cause are
safe to study. It does not enable publication.

## Outputs

The command writes one certificate and nine supporting artifacts:

- `htr010b8_adaptive_evidence_lineage_certificate.json`;
- `htr010b8_candidate_adaptive_evidence_lineage.csv`;
- `htr010b8_point_in_time_outcome_eligibility.csv`;
- `htr010b8_fingerprint_parity_ledger.csv`;
- `htr010b8_shadow_adaptive_assessments.csv`;
- `htr010b8_publication_contract_gap_ledger.csv`;
- `htr010b8_evidence_source_separation.csv`;
- `htr010b8_raw_adjusted_adaptive_comparison.csv`;
- `htr010b8_non_vacuity_probe_ledger.csv`;
- `htr010b8_executive_report.md`.

Every support-file hash, B7 certificate and ledger hash, source-contract hash,
policy hash, and frozen-pipeline hash is bound into the certificate.

## Command

```bash
poetry run python -m alpha benchmark governed-adaptive-evidence-lineage \
  --b7-certificate artifacts/htr010b7/htr010b7_setup_matched_evidence_certificate.json \
  --output artifacts/htr010b8_governed_adaptive_evidence_lineage
```

## Governance

Every B8 certificate records:

- `ADAPTIVE_METADATA_PUBLICATION_ENABLED=false`;
- `APPROVAL_POLICY_CHANGE_PERMITTED=false`;
- `EVIDENCE_THRESHOLD_CHANGE_PERMITTED=false`;
- `FINGERPRINT_MATCHING_CHANGE_PERMITTED=false`;
- `PRODUCTION_LEDGER_MUTATION_ENABLED=false`;
- `SYNTHETIC_OUTCOMES_PERMITTED=false`;
- `COUNTERFACTUAL_APPROVAL_CLAIMED=false`;
- `GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false`;
- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

Any publication bridge, fingerprint-schema repair, outcome-ledger mutation,
threshold change, setup-matching change, trade research, economic claim, or
production activation requires a separate governed milestone.
