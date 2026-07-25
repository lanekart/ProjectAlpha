# HTR-010B10 Governed Adaptive Institutional Decision and Trade-Formation Shadow Replay

## Purpose

HTR-010B10 exercises the opt-in adaptive metadata publisher certified by
HTR-010B9 through the unchanged institutional-decision and trade-formation stack.
It runs only as a governed shadow replay. The default canonical runtime remains
unchanged and adaptive publication remains disabled unless the B10 engine injects
the publisher explicitly.

The milestone answers a narrow question: after exact point-in-time adaptive
metadata reaches the institutional consumer, which approval gates, portfolio
eligibility states, and frozen recorded-plan trades change? It does not optimise
policy or claim economic superiority.

## Signed handoff

The command requires ready, hash-bound certificates for:

- HTR-010B9 adaptive publication bridge;
- HTR-010B8 adaptive evidence lineage;
- HTR-010B7 setup-matched evidence sufficiency.

It also requires the exact identity, corporate-action, final-closure, admission,
identity-admission, RAW-universe, and ADJUSTED-universe artifacts already bound by
B7. B10 verifies the B9→B8→B7 report and certificate-file chain, validates every
B7 input-file hash, and rebuilds the governed RAW and ADJUSTED stores rather than
trusting a moving directory.

## Two-pass replay

### 1. Immutable default pass

B10 first runs the unchanged canonical pipeline chronologically for each price
arm with adaptive publication disabled. It preserves:

- immutable recommendation objects;
- market regime and institutional decisions;
- allocation reports;
- recorder-generated recommendation-ledger entries;
- frozen recorded-plan outcomes from the existing trade simulator.

Only BUY and STRONG_BUY recommendations enter the adaptive evidence ledger. RAW
and ADJUSTED entries and outcomes are isolated permanently and are never pooled.

### 2. Adaptive-published shadow pass

B10 reruns the same dates and stores with an injected
`PointInTimeAdaptiveMetadataPublisher`. For each recommendation, the publisher may
use only exact-fingerprint outcomes whose ledger date and completion date are both
strictly before the current recommendation date. Pending, active, not-triggered,
missing, same-date, future, incomplete, and fingerprint-mismatched evidence stays
excluded.

The five authorised metadata fields are:

- `adaptive_adjusted_confidence`;
- `adaptive_evidence_strength`;
- `adaptive_posterior_probability`;
- `adaptive_expectancy`;
- `adaptive_sample_count`.

## Comparison and attribution

B10 compares DEFAULT and ADAPTIVE_PUBLISHED candidates by price arm, decision date,
and symbol.

Recommendation objects must be identical after removing only the five authorised
adaptive keys. Any other recommendation, trade-plan, price, setup, or risk-field
change is semantic drift and blocks readiness.

Institutional comparison records:

- adaptive evidence values;
- opportunity score and grade;
- acceptance state;
- full rejection-code set and primary gate;
- approval and gate transitions;
- whether the transition is attributable to the adaptive consumer contract.

Only transitions involving the existing adaptive-sensitive gates are explainable:
`INSUFFICIENT_EVIDENCE`, `POOR_HISTORICAL_EDGE`, `WEAK_CONFIDENCE`, and
`WEAK_SETUP`. No new gate or threshold is introduced.

Portfolio and trade comparison records the unchanged allocation amount, portfolio
eligibility, shadow trade formation, entry status, and completed recorded-plan
outcome. Adaptive metadata is not permitted to alter allocation policy, entry,
stop, targets, execution assumptions, or a paired trade's realised result.

## RAW and ADJUSTED separation

B10 compares adaptive effects across RAW and ADJUSTED arms without merging their
evidence. A different adaptive effect is explained only when the signed B7 input
fingerprint differs. An effect difference with unchanged signed inputs blocks
readiness.

## Zero approvals and zero trades

A zero-approval or zero-trade real-data result is not itself a defect. It may be
the correct result of the unchanged institutional gates. Readiness certifies the
point-in-time shadow path and its attribution contract, not the existence of an
economic edge.

## Readiness states

- `READY_FOR_GOVERNED_ADAPTIVE_INSTITUTIONAL_TRADE_SHADOW_RESEARCH`
- `BLOCKED_BY_EMPTY_ADAPTIVE_SHADOW_POPULATION`
- `BLOCKED_BY_B9_HANDOFF_DEFECT`
- `BLOCKED_BY_DEFAULT_PATH_DRIFT`
- `BLOCKED_BY_POINT_IN_TIME_ADAPTIVE_LEAKAGE`
- `BLOCKED_BY_RECOMMENDATION_SEMANTIC_DRIFT`
- `BLOCKED_BY_UNEXPLAINED_INSTITUTIONAL_DECISION_DIVERGENCE`
- `BLOCKED_BY_UNEXPLAINED_TRADE_FORMATION_DIVERGENCE`
- `BLOCKED_BY_UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCE`
- `BLOCKED_BY_ADAPTIVE_SHADOW_IMPLEMENTATION_DEFECT`

## Outputs

The command writes one signed certificate and eleven deterministic support files:

- `htr010b10_adaptive_institutional_trade_shadow_certificate.json`;
- `htr010b10_adaptive_publication_ledger.csv`;
- `htr010b10_institutional_decision_comparison.csv`;
- `htr010b10_gate_transition_ledger.csv`;
- `htr010b10_portfolio_trade_formation_comparison.csv`;
- `htr010b10_completed_trade_outcome_comparison.csv`;
- `htr010b10_point_in_time_eligibility.csv`;
- `htr010b10_raw_adjusted_effect_comparison.csv`;
- `htr010b10_default_path_invariance.csv`;
- `htr010b10_source_contract_snapshot.csv`;
- `htr010b10_non_vacuity_probe_ledger.csv`;
- `htr010b10_executive_report.md`.

Every support-file hash, upstream certificate hash, explicit input hash, and frozen
source-contract hash is bound into the certificate.

## Command

```bash
poetry run python -m alpha benchmark governed-adaptive-institutional-trade-shadow \
  --b9-certificate artifacts/htr010b9/htr010b9_adaptive_publication_bridge_certificate.json \
  --b8-certificate artifacts/htr010b8/htr010b8_adaptive_evidence_lineage_certificate.json \
  --b7-certificate artifacts/htr010b7/htr010b7_setup_matched_evidence_certificate.json \
  --identity-artifact artifacts/identity/htr010b1_canonical_identity_timeline.json \
  --corporate-action-artifact artifacts/actions/htr010b1_canonical_action_timeline.json \
  --final-closure-report artifacts/closure/htr010b1_final_closure_report.json \
  --admission-contract artifacts/admission/htr010b1h_replay_contract.json \
  --identity-admission artifacts/admission/htr010b1h_identity_admission.json \
  --raw-universe artifacts/admission/htr010b1h_raw_universe.json \
  --adjusted-universe artifacts/admission/htr010b1h_adjusted_universe.json \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --output artifacts/htr010b10_governed_adaptive_institutional_trade_shadow
```

## Guardrails

Every B10 certificate records:

- `DEFAULT_RUNTIME_ADAPTIVE_PUBLICATION_ENABLED=false`;
- `APPROVAL_POLICY_CHANGE_PERMITTED=false`;
- `EVIDENCE_THRESHOLD_CHANGE_PERMITTED=false`;
- `FINGERPRINT_MATCHING_CHANGE_PERMITTED=false`;
- `PORTFOLIO_POLICY_CHANGE_PERMITTED=false`;
- `EXECUTION_POLICY_CHANGE_PERMITTED=false`;
- `PRODUCTION_LEDGER_MUTATION_ENABLED=false`;
- `SYNTHETIC_OUTCOMES_PERMITTED=false`;
- `COUNTERFACTUAL_APPROVAL_CLAIMED=false`;
- `ECONOMIC_SUPERIORITY_CLAIMED=false`;
- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

A ready B10 certificate permits only governed adaptive institutional and
trade-formation shadow research. Production activation, policy optimisation,
threshold changes, portfolio deployment, and live scoring require separate
signed milestones.

## Acceptance source pin

Repository validation and signed real-data acceptance must run from a clean
worktree at the exact reviewed B10 commit SHA recorded on the pull request. A
moving branch name is not an acceptance identity. Record both the internal report
SHA-256 and the certificate-file SHA-256 before changing the branch or removing
the acceptance worktree. Repository Lint and CI must both pass on that exact
source commit before acceptance begins.
