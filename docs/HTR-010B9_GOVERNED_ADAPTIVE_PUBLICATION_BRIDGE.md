# HTR-010B9 Governed Point-in-Time Adaptive Metadata Publication Bridge

## Purpose

HTR-010B9 implements and certifies the narrow integration contract identified by
HTR-010B8. It adds an explicit, dependency-injected seam that can enrich immutable
recommendation reports with point-in-time adaptive evidence metadata while leaving
the default canonical runtime unchanged.

The milestone does not change evidence thresholds, fingerprint matching, approval
policy, recommendation scoring, portfolio rules, execution policy, Historical
Truth policy, or production behavior.

## Signed handoff

The B9 command requires a signed HTR-010B8 certificate in
`READY_FOR_GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH` state. The B8 certificate
and every bound support artifact are validated before B9 reads the shadow adaptive
assessment ledger.

B9 intentionally validates the B8 certificate without requiring the old B8 source
hashes to equal the current source tree because B9 is the governed source evolution
that repairs the certified publication and recorder gaps. It separately verifies
that only the source contracts authorised by this milestone changed.

## Read-only point-in-time publisher

`PointInTimeAdaptiveMetadataPublisher` receives immutable recommendation-ledger
entries and outcomes. For a recommendation on date `T`, a ledger sample is eligible
only when:

- its full existing `SetupFingerprint` exactly matches the recommendation;
- the ledger entry was generated before `T`;
- the outcome is `EXITED` or `EXPIRED`;
- realised R is available;
- the outcome exit date exists and is strictly earlier than `T`.

Same-date entries, same-date completions, future completions, pending outcomes,
missing completion dates, missing realised R, fingerprint mismatches, and absent
outcomes remain excluded.

The existing `AdaptiveLearningEngine` calculates the assessment. B9 does not create
a replacement estimator.

## Published metadata contract

The opt-in publisher writes exactly the five keys already consumed by the
institutional adapter:

```text
adaptive_adjusted_confidence
adaptive_evidence_strength
adaptive_posterior_probability
adaptive_expectancy
adaptive_sample_count
```

Recommendation reports remain frozen dataclasses; publication returns replaced
immutable reports whose pre-existing metadata is preserved.

## Explicit runtime seam

`IntelligenceApplicationService` and `CanonicalAlphaRunner` expose:

```text
adaptive_metadata_publication_enabled=False
adaptive_metadata_publisher=None
```

The publisher is not invoked when the flag is false. Enabling the flag without a
publisher fails closed. This milestone certifies that the default runtime output is
identical to the pre-publication path.

B9 does not turn the flag on in the canonical benchmark, production runtime, live
scoring, or any command other than the governed shadow certification.

## Fingerprint-recorder repair

Future recommendation ledger entries now preserve the two fingerprint dimensions
that HTR-010B8 found missing from `key_indicator_snapshot`:

```text
candle_pattern
retracement_state
```

The existing fingerprint schema and matching policy are unchanged. Existing ledger
rows are not edited or backfilled. The B9 certificate exercises the real
recommendation-to-ledger recorder and requires exact parity between
`fingerprint_from_recommendation()` and `fingerprint_from_ledger_entry()`.

## B8 shadow transport boundary

The signed B8 shadow assessment rows are used only to certify deterministic
five-field transport and RAW/ADJUSTED parity. Their coarse B7/B8 reconstruction is
not promoted into an authoritative operational full-fingerprint ledger.

Production publication requires an explicitly injected read-only publisher backed
by immutable ledger entries and outcomes. No B8 CSV is wired into the normal
application path.

## Certification

B9 certifies:

- all five metadata fields survive recommendation metadata and institutional
  parsing;
- malformed numeric metadata fails closed;
- the default disabled path never calls the publisher and produces identical
  output;
- the publisher includes only strictly prior completed exact-fingerprint outcomes;
- the repaired future recorder produces exact fingerprint parity;
- signed B8 RAW and ADJUSTED shadow transport remains paired and unexplained
  divergences are zero;
- source evolution is limited to the authorised publication and recorder seams;
- deterministic non-vacuity probes pass;
- all production and policy influence remains disabled.

## Readiness states

- `READY_FOR_GOVERNED_ADAPTIVE_PUBLICATION_SHADOW_REPLAY`
- `BLOCKED_BY_ADAPTIVE_PUBLICATION_ROUND_TRIP_DEFECT`
- `BLOCKED_BY_FINGERPRINT_RECORDER_PARITY_DEFECT`
- `BLOCKED_BY_DEFAULT_PATH_DRIFT`
- `BLOCKED_BY_POINT_IN_TIME_PUBLICATION_LEAKAGE`
- `BLOCKED_BY_ADAPTIVE_PUBLICATION_IMPLEMENTATION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_PUBLICATION_ARM_DIVERGENCE`

Ready means only that the opt-in transport and recorder contracts are safe for a
governed shadow replay. It does not enable canonical or production publication.

## Outputs

The command writes one certificate and eight bound support artifacts:

- `htr010b9_adaptive_publication_bridge_certificate.json`;
- `htr010b9_publication_round_trip_ledger.csv`;
- `htr010b9_default_path_invariance.csv`;
- `htr010b9_fingerprint_recorder_parity.csv`;
- `htr010b9_point_in_time_publication_eligibility.csv`;
- `htr010b9_raw_adjusted_transport_comparison.csv`;
- `htr010b9_source_contract_snapshot.csv`;
- `htr010b9_non_vacuity_probe_ledger.csv`;
- `htr010b9_executive_report.md`.

Every support-file hash, B8 input hash, and current source-contract hash is bound
into the certificate.

## Command

```bash
poetry run python -m alpha benchmark governed-adaptive-publication-bridge \
  --b8-certificate artifacts/htr010b8/htr010b8_adaptive_evidence_lineage_certificate.json \
  --output artifacts/htr010b9_governed_adaptive_publication_bridge
```

## Governance

Every certificate records:

```text
DEFAULT_RUNTIME_ADAPTIVE_PUBLICATION_ENABLED=false
APPROVAL_POLICY_CHANGE_PERMITTED=false
EVIDENCE_THRESHOLD_CHANGE_PERMITTED=false
FINGERPRINT_MATCHING_CHANGE_PERMITTED=false
PRODUCTION_LEDGER_BACKFILL_ENABLED=false
SYNTHETIC_OUTCOMES_PERMITTED=false
COUNTERFACTUAL_APPROVAL_CLAIMED=false
GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false
LIVE_SCORING_ENABLED=false
RECOMMENDATION_INFLUENCE=false
PORTFOLIO_POLICY_INFLUENCE=false
EXECUTION_INFLUENCE=false
LEARNING_MUTATION_ENABLED=false
ACTIVE_REPLAY_INTEGRATION=false
PRODUCTION_INFLUENCE=false
```

Any activation of the publication flag in the canonical benchmark, any approval or
trade effect, any backfill, or any production integration belongs to a later
separately accepted milestone.
