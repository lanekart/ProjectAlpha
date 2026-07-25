# HTR-010B10 Governed Adaptive Institutional and Trade Shadow Replay

## Purpose

HTR-010B10 extends the signed HTR-010B9 publication bridge into an isolated,
research-only institutional and trade-formation shadow contract. The default runtime
continues to keep adaptive publication disabled.

The milestone validates the signed B9 → B8 → B7 lineage, binds the governed identity,
action, closure, admission, and universe inputs, preserves all policy and execution
boundaries, and emits a deterministic signed certificate plus support ledgers.

## Fail-closed boundary

The engine must not manufacture adaptive observations, approvals, allocations, trades,
or economic outcomes. Until the existing governed replay and publisher seams supply a
non-empty empirical shadow population, B10 returns
`BLOCKED_BY_EMPTY_ADAPTIVE_SHADOW_POPULATION` while still certifying handoff,
readiness precedence, support-artifact hashing, tamper detection, and governance flags.

A zero-trade result is not itself a defect. A ready state requires a non-empty adaptive
shadow population and zero unexplained default drift, point-in-time leakage,
recommendation semantic drift, institutional divergence, trade-formation divergence,
arm divergence, handoff defect, or implementation defect.

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

The command writes one certificate and eleven deterministic support artifacts:

- `htr010b10_adaptive_institutional_trade_shadow_certificate.json`
- `htr010b10_adaptive_publication_ledger.csv`
- `htr010b10_institutional_decision_comparison.csv`
- `htr010b10_gate_transition_ledger.csv`
- `htr010b10_portfolio_trade_formation_comparison.csv`
- `htr010b10_completed_trade_outcome_comparison.csv`
- `htr010b10_point_in_time_eligibility.csv`
- `htr010b10_raw_adjusted_effect_comparison.csv`
- `htr010b10_default_path_invariance.csv`
- `htr010b10_source_contract_snapshot.csv`
- `htr010b10_non_vacuity_probe_ledger.csv`
- `htr010b10_executive_report.md`

## Governance

Every certificate records that default adaptive publication, policy changes, threshold
changes, fingerprint changes, portfolio-policy changes, execution-policy changes,
production-ledger mutation, synthetic outcomes, counterfactual approval claims,
economic-superiority claims, live scoring, recommendation influence, portfolio
influence, execution influence, learning mutation, active replay integration, and
production influence are all disabled.

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
